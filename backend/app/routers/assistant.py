"""AI から話しかける機能と、「ねえ○○」で起きる機能の設定。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import Field

from app.calendar.google import GoogleError
from app.calendar.service import CalendarError
from app.deps import Services, get_services
from app.errors import AppError, setup_required
from app.llm.ollama import OllamaError
from app.schemas import SELF_PROFILE_FIELDS, StrictModel
from app.services import proactive
from app.services.persona import build_system_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["assistant"])

WAKE_CONSENT_KIND = "wake_word"
WAKE_CONSENT_VERSION = "2026-11-04.1"


class ProactiveRequest(StrictModel):
    # 最後に会話してから何分たったか（画面側が数える。保存しない会話もあるため）
    idle_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 365)


@router.post("/proactive/next")
async def proactive_next(body: ProactiveRequest, services: Services = Depends(get_services)) -> dict:
    """いま話しかけることがあれば、その言葉を作って返す。なければ kind は null。"""
    if not services.settings.is_setup_completed():
        raise setup_required()
    settings = services.settings.get()
    if not settings.proactive_enabled or services.training.running:
        return {"kind": None}
    now = proactive.now()
    if proactive.in_quiet_hours(now, settings.quiet_start, settings.quiet_end):
        return {"kind": None}

    events = []
    if services.calendar.is_connected():
        try:
            events = await services.calendar.upcoming(days=1)
        except (GoogleError, CalendarError) as exc:
            logger.warning("Calendar unavailable for proactive talk: %s", type(exc).__name__)
    log = proactive.ProactiveLog(services.db)
    occasion = proactive.find_occasion(settings, now, events, body.idle_minutes, log.sent_keys(), log.last_idle_at())
    if occasion is None:
        return {"kind": None}

    profile = services.profile.list()
    user_name = next((e.content for e in profile if e.key == "self.user_name"), "")
    system_prompt = build_system_prompt(settings.ai_name, profile, language=settings.language)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": proactive.build_instruction(occasion, user_name)},
    ]
    try:
        text = await services.ollama.chat_once(
            settings.model, messages, {"temperature": settings.temperature, "num_ctx": settings.num_ctx}
        )
    except OllamaError as exc:
        logger.warning("Proactive talk failed: %s", exc.code)
        return {"kind": None}
    text = text.strip()
    if not text:
        return {"kind": None}
    log.mark(occasion.key)
    return {"kind": occasion.kind, "text": text}


# ---------- 「ねえ○○」で起きる ----------


def _wake_missing(services: Services) -> list[str]:
    """「あなたのこと」で、まだ入力されていない項目。すべて入力されるまで使えない。"""
    settings = services.settings.get()
    filled = {e.key for e in services.profile.list() if e.content.strip()}
    missing = [] if settings.ai_name.strip() else ["AIの名前"]
    missing += [label for key, label in SELF_PROFILE_FIELDS.items() if key not in filled]
    if not settings.language:
        missing.append("言語")
    return missing


@router.get("/wake/status")
def wake_status(services: Services = Depends(get_services)) -> dict:
    missing = _wake_missing(services)
    return {"enabled": services.settings.get().wake_enabled, "ready": not missing, "missing": missing}


class WakeRequest(StrictModel):
    enabled: bool
    # オンにするときは、マイクを常に聞くことへの同意が必要
    consent: bool = False


@router.post("/wake")
def set_wake(body: WakeRequest, services: Services = Depends(get_services)) -> dict:
    if not services.settings.is_setup_completed():
        raise setup_required()
    if body.enabled:
        missing = _wake_missing(services)
        if missing:
            raise AppError(
                409, "profile_incomplete", f"先に設定の「あなたのこと」で、次の項目を入力してください: {'、'.join(missing)}"
            )
        if not body.consent:
            raise AppError(400, "consent_required", "マイクを常に聞くことへの同意が必要です。")
        with services.db.transaction() as conn:
            services.profile.record_consent(conn, WAKE_CONSENT_KIND, WAKE_CONSENT_VERSION, True)
    services.settings.update({"wake_enabled": body.enabled})
    return wake_status(services)
