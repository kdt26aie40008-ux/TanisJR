"""会話からカレンダー操作の「下書き」を作る。実行はしない（ユーザーの承認が必要）。"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.calendar.models import CalendarEvent, EventDraft, OperationCreate, local_now, to_local
from app.llm.ollama import OllamaClient

logger = logging.getLogger(__name__)

WEEKDAYS = "月火水木金土日"

# 予定に関する発言のときだけ LLM で下書きを作る（毎回の推論コストを避ける）
_CALENDAR_HINT = re.compile(
    r"予定|カレンダー|スケジュール|リマインド|アポ|約束|会議|ミーティング|打ち合わせ|締め切り|締切|"
    r"(入れて|追加|登録|変更|ずらし|移動|キャンセル|取り消|削除|消して)"
)


def mentions_calendar(text: str) -> bool:
    return bool(_CALENDAR_HINT.search(text))


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["none", "create", "update", "delete"]},
        "event_id": {"type": "string"},
        "summary": {"type": "string"},
        "all_day": {"type": "boolean"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "location": {"type": "string"},
        "reminder_minutes": {"type": "integer"},
    },
    "required": ["action"],
}

SYSTEM_PROMPT = """\
あなたはユーザーの発言から Google カレンダーの操作内容を読み取る担当です。実行はしません。

## ルール
- ユーザーが予定の追加・変更・削除を **はっきり依頼している** ときだけ action を create / update / delete にする。
  予定について話しているだけ、質問しているだけ（「明日の予定は？」など）のときは action を "none" にする。
- update / delete の event_id は、下の「既存の予定」の id から選ぶ。該当が分からなければ "none" にする。
- 日時は今日の日付を基準に解釈する。時刻付きは "YYYY-MM-DDTHH:MM"、終日は all_day=true で "YYYY-MM-DD"。
- 終了時刻が分からなければ開始の1時間後にする。
- 推測で場所や内容を付け足さない。
- reminder_minutes はユーザーが「◯分前に知らせて」などと言った場合だけ入れる。"""


class _Raw(BaseModel):
    action: Literal["none", "create", "update", "delete"]
    event_id: str = ""
    summary: str = ""
    all_day: bool = False
    start: str = ""
    end: str = ""
    location: str = ""
    reminder_minutes: int | None = None


def build_messages(user_text: str, events: list[CalendarEvent]) -> list[dict[str, str]]:
    now = local_now()
    listing = "\n".join(f"- id={e.id} | {e.start} 〜 {e.end} | {e.summary}" for e in events) or "（なし）"
    context = (
        f"今日: {now:%Y-%m-%d}（{WEEKDAYS[now.weekday()]}） 現在時刻 {now:%H:%M}\n\n"
        f"## 既存の予定（直近）\n{listing}\n\n"
        f"## ユーザーの発言\n<user>\n{user_text}\n</user>"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": context}]


def parse_proposal(raw: str, events: list[CalendarEvent]) -> OperationCreate | None:
    try:
        data = _Raw.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        logger.warning("Calendar proposal returned an invalid response")
        return None
    if data.action == "none":
        return None
    known = {e.id: e for e in events}
    try:
        if data.action == "delete":
            if data.event_id not in known:
                return None
            return OperationCreate(action="delete", event_id=data.event_id)
        if data.action == "update" and data.event_id not in known:
            return None
        start, end = data.start, data.end
        if not data.all_day and start and not end:
            end = (to_local(start) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        if data.all_day and start and not end:
            end = start
        if data.action == "update":
            # 変更では言及されなかった項目を元の予定から引き継ぐ
            base = known[data.event_id]
            draft = EventDraft(
                summary=data.summary or base.summary,
                all_day=data.all_day if start else base.all_day,
                start=start or base.start[:16],
                end=end or base.end[:16],
                location=data.location or base.location,
                description=base.description,
                reminder_minutes=data.reminder_minutes,
            )
            return OperationCreate(action="update", event_id=data.event_id, draft=draft)
        draft = EventDraft(
            summary=data.summary,
            all_day=data.all_day,
            start=start,
            end=end,
            location=data.location,
            reminder_minutes=data.reminder_minutes,
        )
        return OperationCreate(action="create", draft=draft)
    except (ValueError, ValidationError):
        logger.warning("Calendar proposal could not be converted to a valid draft")
        return None


async def propose_from_text(
    client: OllamaClient, model: str, user_text: str, events: list[CalendarEvent]
) -> OperationCreate | None:
    raw = await client.chat_once(
        model, build_messages(user_text, events), {"temperature": 0.0, "num_ctx": 4096}, response_format=RESPONSE_SCHEMA
    )
    return parse_proposal(raw, events)


def calendar_context(events: list[CalendarEvent]) -> str:
    """会話用のシステムプロンプトに追加する、直近の予定と操作のルール。"""
    lines = [
        "## ユーザーの Google カレンダー（直近7日）",
        *(
            [f"- {e.start[:16].replace('T', ' ')} 〜 {e.end[11:16] if not e.all_day else '終日'} {e.summary}" for e in events]
            or ["（予定はありません）"]
        ),
        "",
        "## カレンダー操作のルール",
        "- あなたは予定を直接追加・変更・削除できない。依頼されたら内容を確認するように答える。",
        "- 画面に表示される確認カードでユーザーが「承認」を押したときだけ実行される。まだ実行されていないので「追加しました」「削除しました」とは言わない。",
    ]
    return "\n".join(lines)
