from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.calendar.google import GoogleError
from app.calendar.models import CalendarEvent
from app.calendar.proposals import calendar_context, mentions_calendar, propose_from_text
from app.calendar.service import CalendarError
from app.deps import Services, get_services
from app.llm.ollama import OllamaError
from app.errors import AppError, setup_required
from app.routers.sse import sse_response
from app.schemas import ChatRequest
from app.services.chat import stream_chat
from app.services.persona import build_system_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

CATEGORY_LABELS = {
    "preference": "好み",
    "habit": "習慣・傾向",
    "fact": "事実",
    "personal": "個人情報",
    "personality": "性格",
    "values": "価値観",
    "other": "その他",
}


@dataclass
class _Turn:
    text: str = ""
    message_id: int | None = None


@router.post("/chat")
async def chat(body: ChatRequest, services: Services = Depends(get_services)) -> StreamingResponse:
    if not services.settings.is_setup_completed():
        raise setup_required()
    if services.training.running:
        # 学習と会話モデルが同時に GPU を使うとメモリが不足し、学習が失敗する（実機で確認）
        raise AppError(503, "training_running", "追加学習を実行中のため、終わるまで会話できません。学習管理画面で進み具合を確認できます。")
    conversation_id = body.conversation_id
    if conversation_id and not services.conversations.exists(conversation_id):
        raise AppError(404, "conversation_not_found", "保存先の会話が見つかりません。削除された可能性があります。")

    settings = services.settings.get()
    profile = services.profile.list()
    user_text = body.messages[-1].content
    previous = body.messages[-2] if len(body.messages) >= 2 else None
    previous_assistant = previous.content if previous and previous.role == "assistant" else None

    # 関連する記憶の検索（クエリの埋め込みはメモリ上で一時的に計算するだけで保存しない）
    relevant, notice = await services.memory.relevant(user_text)
    memory_lines = [f"[{CATEGORY_LABELS.get(r.memory.category, r.memory.category)}] {r.memory.content}" for r in relevant]

    # 予定に関する発言のときだけ、直近の予定を会話の文脈に加える
    upcoming: list[CalendarEvent] = []
    calendar_extra = ""
    calendar_notice = None
    use_calendar = services.calendar.is_connected() and mentions_calendar(user_text)
    if use_calendar:
        try:
            upcoming = await services.calendar.upcoming(days=7)
            calendar_extra = calendar_context(upcoming)
        except (GoogleError, CalendarError) as exc:
            use_calendar = False
            calendar_notice = f"カレンダーを読み込めませんでした: {exc.message}"

    system_prompt = build_system_prompt(
        settings.ai_name,
        profile,
        memory_lines,
        extra=calendar_extra,
        language=settings.language,
        # 時刻に合ったあいさつをするため
        time_of_day=datetime.now().strftime("%H:%M"),
    )
    turn = _Turn()

    async def calendar_proposal() -> dict[str, Any] | None:
        """予定の追加・変更・削除の依頼なら、承認待ちの下書きを作る（ここでは実行しない）。"""
        if not (use_calendar and settings.calendar_ai_proposals):
            return None
        try:
            proposal = await propose_from_text(services.ollama, settings.model, user_text, upcoming)
            if proposal is None:
                return None
            op = await services.calendar.propose(proposal, source="ai")
        except (OllamaError, GoogleError, CalendarError) as exc:
            logger.warning("Calendar proposal failed: %s", type(exc).__name__)
            return None
        return {"type": "calendar_proposal", "operation": op.model_dump(mode="json")}

    async def events() -> AsyncIterator[dict[str, Any]]:
        for message in (notice, calendar_notice):
            if message:
                yield {"type": "notice", "message": message}
        if relevant:
            yield {
                "type": "memories_used",
                "items": [{"id": r.memory.id, "content": r.memory.content, "category": r.memory.category} for r in relevant],
            }
        async for event in stream_chat(services.ollama, settings, system_prompt, body.messages):
            if event["type"] == "token":
                turn.text += event["content"]
            elif event["type"] == "done" and conversation_id and turn.text.strip():
                # 保存を許可された会話のみ、完了したターンを保存する
                try:
                    turn.message_id = services.conversations.append_turn(conversation_id, user_text, turn.text)
                    yield {"type": "saved", "conversation_id": conversation_id}
                except KeyError:
                    yield {"type": "notice", "message": "会話が削除されたため、このやり取りは保存されませんでした。"}
            if event["type"] == "done" and turn.text.strip():
                proposal = await calendar_proposal()
                if proposal:
                    yield proposal
            yield event

    async def extract() -> None:
        if conversation_id is None or turn.message_id is None or services.training.running:
            return
        try:
            await services.memory.process_exchange(conversation_id, turn.message_id, user_text, previous_assistant)
        except Exception as exc:  # noqa: BLE001  応答後の処理なので失敗しても会話は継続させる
            logger.error("Memory extraction error: %s", type(exc).__name__)

    # 記憶抽出は応答を送り終えた後に行う（保存しない会話では実行しない）
    return sse_response(events(), background=BackgroundTask(extract) if conversation_id else None)
