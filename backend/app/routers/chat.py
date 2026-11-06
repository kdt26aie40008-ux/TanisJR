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
from app.calendar.conversation import classify_reply, outcome_instruction, proposal_instruction, revise
from app.calendar.models import CalendarEvent, Operation, OperationCreate
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


def _op_event(kind: str, op: Operation) -> dict[str, Any]:
    return {"type": kind, "operation": op.model_dump(mode="json")}


async def _propose(
    services: Services, model: str, text: str, upcoming: list[CalendarEvent]
) -> Operation | None:
    """予定の追加・変更・削除の依頼なら、確認待ちの下書きを作る（ここでは実行しない）。"""
    try:
        proposal = await propose_from_text(services.ollama, model, text, upcoming)
        return await services.calendar.propose(proposal, source="ai") if proposal else None
    except (OllamaError, GoogleError, CalendarError) as exc:
        logger.warning("Calendar proposal failed: %s", type(exc).__name__)
        return None


async def _calendar_turn(
    services: Services,
    model: str,
    user_text: str,
    upcoming: list[CalendarEvent],
    awaiting: Operation | None,
) -> tuple[str, list[dict[str, Any]]]:
    """会話での予定の確認を進める。返り値は（AI への指示, 画面に送るイベント）。

    - 確認中の下書きがなければ、依頼から下書きを作り、復唱して確認するよう AI に指示する。
    - 確認中の下書きがあれば、ユーザーの返事が了承なら実行、断りなら破棄、直す指示なら作り直す。
      はっきりしない返事では実行しない（画面のカードのボタンでも決められる）。
    """
    calendar = services.calendar
    if awaiting is None:
        if not mentions_calendar(user_text):
            return "", []
        op = await _propose(services, model, user_text, upcoming)
        return (proposal_instruction(op), [_op_event("calendar_proposal", op)]) if op else ("", [])

    reply = await classify_reply(services.ollama, model, awaiting, user_text)
    if reply.decision == "yes":
        op = awaiting
        try:
            if reply.reminder_minutes is not None:
                op = calendar.set_reminder(op.id, reply.reminder_minutes)
            done = await calendar.approve(op.id)
            instruction = outcome_instruction("yes", done)
            if reply.no_reminder and done.result_event_id:
                # 「通知はいらない」と言われたら、この予定は通知しない
                calendar.set_notify(done.result_event_id, -1)
                instruction += "\n- 通知はしない設定にした。"
            if services.scheduler:
                await services.scheduler.sync(force=True)
            return instruction, [_op_event("calendar_decided", done)]
        except (GoogleError, CalendarError) as exc:
            latest = calendar.get_operation(op.id) or op
            return outcome_instruction("yes", latest, error=exc.message), [_op_event("calendar_decided", latest)]
    if reply.decision == "no":
        rejected = calendar.reject(awaiting.id)
        return outcome_instruction("no", rejected), [_op_event("calendar_decided", rejected)]
    if reply.decision == "change":
        # 直すのは確認中の予定だけ（別の既存の予定を対象にしない）
        draft = await revise(services.ollama, model, awaiting, user_text)
        if draft is not None:
            try:
                op = await calendar.propose(
                    OperationCreate(action=awaiting.action, event_id=awaiting.event_id, draft=draft), source="ai"
                )
            except (GoogleError, CalendarError) as exc:
                logger.warning("Calendar revision failed: %s", type(exc).__name__)
            else:
                rejected = calendar.reject(awaiting.id)
                return proposal_instruction(op), [_op_event("calendar_decided", rejected), _op_event("calendar_proposal", op)]
    # 関係ない話・はっきりしない返事・直し方が分からないとき: 実行せず、最後にもう一度確認する
    return outcome_instruction("other", awaiting), []


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

    # 予定に関する発言、または会話で確認中の予定があるときだけ、カレンダーを会話の文脈に加える
    calendar_on = services.calendar.is_connected() and settings.calendar_ai_proposals
    awaiting = services.calendar.awaiting_confirmation() if calendar_on else None
    upcoming: list[CalendarEvent] = []
    calendar_extra = ""
    calendar_notice = None
    calendar_events: list[dict[str, Any]] = []
    use_calendar = services.calendar.is_connected() and (mentions_calendar(user_text) or awaiting is not None)
    if use_calendar:
        try:
            upcoming = await services.calendar.upcoming(days=7)
            calendar_extra = calendar_context(upcoming)
        except (GoogleError, CalendarError) as exc:
            use_calendar = False
            calendar_notice = f"カレンダーを読み込めませんでした: {exc.message}"

    calendar_flow = ""
    if use_calendar and calendar_on:
        calendar_flow, calendar_events = await _calendar_turn(services, settings.model, user_text, upcoming, awaiting)

    system_prompt = build_system_prompt(
        settings.ai_name,
        profile,
        memory_lines,
        extra=calendar_extra,
        language=settings.language,
        # 時刻に合ったあいさつをするため
        time_of_day=datetime.now().strftime("%H:%M"),
        # 予定の確認の進め方は、守られやすいようプロンプトの最後に置く
        final=calendar_flow,
    )
    turn = _Turn()

    async def events() -> AsyncIterator[dict[str, Any]]:
        for message in (notice, calendar_notice):
            if message:
                yield {"type": "notice", "message": message}
        if relevant:
            yield {
                "type": "memories_used",
                "items": [{"id": r.memory.id, "content": r.memory.content, "category": r.memory.category} for r in relevant],
            }
        # 予定の確認カード（新しい下書き・会話で決まった結果）は、返事より先に送る
        for item in calendar_events:
            yield item
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
