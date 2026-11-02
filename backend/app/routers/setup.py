"""初回設定（同意 → 3つの質問 → AIの名前）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import Services, get_services
from app.errors import AppError
from app.schemas import SetupCompleteRequest
from app.setup_questions import (
    CONSENT_NOTES,
    CONSENT_PURPOSE,
    CONSENT_STORED_ITEMS,
    CONSENT_VERSION,
    SETUP_QUESTIONS,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status")
def status(services: Services = Depends(get_services)) -> dict:
    return {"completed": services.settings.is_setup_completed()}


@router.get("/questions")
def questions() -> dict:
    return {
        "questions": [{"key": q.key, "text": q.text} for q in SETUP_QUESTIONS],
        "consent": {
            "version": CONSENT_VERSION,
            "purpose": CONSENT_PURPOSE,
            "stored_items": list(CONSENT_STORED_ITEMS),
            "notes": list(CONSENT_NOTES),
        },
    }


@router.post("/complete")
def complete(body: SetupCompleteRequest, services: Services = Depends(get_services)) -> dict:
    if not body.consent:
        raise AppError(400, "consent_required", "プロフィールを保存するには、保存内容と利用目的への同意が必要です。")
    if services.settings.is_setup_completed():
        raise AppError(409, "setup_already_completed", "初回設定はすでに完了しています。")

    # 同意・回答・AI名をまとめて保存し、途中で失敗したら何も残さない
    with services.db.transaction() as conn:
        services.profile.record_consent(conn, "initial_profile", CONSENT_VERSION, True)
        for question, answer in zip(SETUP_QUESTIONS, body.answers, strict=True):
            services.profile.insert(conn, question.key, question.text, answer)
        services.settings.update({"ai_name": body.ai_name}, conn=conn)
        services.settings.mark_setup_completed(conn)
    return {"completed": True, "ai_name": body.ai_name}
