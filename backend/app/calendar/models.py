"""カレンダーの予定・操作の下書きのデータ型と、Google API 形式との変換。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import clean_text

Action = Literal["create", "update", "delete"]


def local_now() -> datetime:
    return datetime.now().astimezone()


def to_local(value: str) -> datetime:
    """'YYYY-MM-DDTHH:MM' 形式（タイムゾーンなし）はこのPCの時刻として解釈する。"""
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone() if parsed.tzinfo is None else parsed


class EventDraft(BaseModel):
    """予定の内容（追加・変更時）。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=200)
    all_day: bool = False
    # 時刻付き: 'YYYY-MM-DDTHH:MM'（ローカル時刻）/ 終日: 'YYYY-MM-DD'
    start: str = Field(min_length=10, max_length=40)
    end: str = Field(min_length=10, max_length=40)
    location: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    # Google カレンダー側のリマインダー（分前）。None はカレンダーの既定
    reminder_minutes: int | None = Field(default=None, ge=0, le=40320)

    @field_validator("summary", "location", "description")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_text(value)

    @model_validator(mode="after")
    def _check_range(self) -> EventDraft:
        if not self.summary:
            raise ValueError("予定のタイトルを入力してください。")
        try:
            if self.all_day:
                start, end = date.fromisoformat(self.start[:10]), date.fromisoformat(self.end[:10])
                self.start, self.end = start.isoformat(), end.isoformat()
                if end < start:
                    raise ValueError("終了日は開始日以降にしてください。")
            else:
                s, e = to_local(self.start), to_local(self.end)
                if e <= s:
                    raise ValueError("終了時刻は開始時刻より後にしてください。")
        except ValueError as exc:
            if "してください" in str(exc):
                raise
            raise ValueError("日時の形式が正しくありません。") from exc
        return self

    def to_google(self) -> dict[str, Any]:
        body: dict[str, Any] = {"summary": self.summary, "location": self.location, "description": self.description}
        if self.all_day:
            # Google の終日予定は終了日を「翌日」で指定する
            end = date.fromisoformat(self.end) + timedelta(days=1)
            body["start"] = {"date": self.start}
            body["end"] = {"date": end.isoformat()}
        else:
            body["start"] = {"dateTime": to_local(self.start).isoformat()}
            body["end"] = {"dateTime": to_local(self.end).isoformat()}
        if self.reminder_minutes is not None:
            body["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": self.reminder_minutes}]}
        return body

    def to_event(self, event_id: str) -> CalendarEvent:
        """アプリ内カレンダーに保存する形にする（時刻はこの PC のタイムゾーン付き）。"""
        return CalendarEvent(
            id=event_id,
            summary=self.summary,
            all_day=self.all_day,
            start=self.start if self.all_day else to_local(self.start).isoformat(),
            end=self.end if self.all_day else to_local(self.end).isoformat(),
            location=self.location,
            description=self.description,
        )


class CalendarEvent(BaseModel):
    id: str
    summary: str
    all_day: bool
    start: str  # ISO 8601（時刻付きはオフセット付き、終日は日付）
    end: str
    location: str = ""
    description: str = ""
    html_link: str = ""
    # このアプリでの通知（分前）。None は既定値、-1 は通知しない
    notify_minutes: int | None = None

    @classmethod
    def from_google(cls, item: dict[str, Any]) -> CalendarEvent:
        start, end = item.get("start") or {}, item.get("end") or {}
        all_day = "date" in start
        if all_day:
            # 表示用に「最終日」に戻す
            last = date.fromisoformat(end.get("date", start["date"])) - timedelta(days=1)
            start_s, end_s = start["date"], max(last, date.fromisoformat(start["date"])).isoformat()
        else:
            start_s, end_s = start.get("dateTime", ""), end.get("dateTime", "")
        return cls(
            id=str(item["id"]),
            summary=str(item.get("summary") or "（タイトルなし）"),
            all_day=all_day,
            start=start_s,
            end=end_s,
            location=str(item.get("location") or ""),
            description=str(item.get("description") or "")[:2000],
            html_link=str(item.get("htmlLink") or ""),
        )

    def start_dt(self) -> datetime:
        if self.all_day:
            return datetime.combine(date.fromisoformat(self.start), datetime.min.time()).astimezone()
        return to_local(self.start)

    def end_dt(self) -> datetime:
        if self.all_day:
            return datetime.combine(date.fromisoformat(self.end) + timedelta(days=1), datetime.min.time()).astimezone()
        return to_local(self.end)


class Operation(BaseModel):
    id: str
    action: Action
    event_id: str | None
    draft: EventDraft | None
    # 変更・削除の対象として表示する、操作前の予定の内容
    target: CalendarEvent | None
    source: Literal["user", "ai"]
    status: Literal["pending", "done", "rejected", "failed"]
    error: str | None
    result_event_id: str | None
    created_at: str
    decided_at: str | None


class OperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    event_id: str | None = Field(default=None, max_length=1024, pattern=r"^[A-Za-z0-9_\-]+$")
    draft: EventDraft | None = None

    @model_validator(mode="after")
    def _check(self) -> OperationCreate:
        if self.action in ("update", "delete") and not self.event_id:
            raise ValueError("対象の予定が指定されていません。")
        if self.action in ("create", "update") and self.draft is None:
            raise ValueError("予定の内容が指定されていません。")
        return self


class NotifyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None: 既定値に戻す / -1: 通知しない / 0以上: 何分前に通知するか
    minutes: int | None = Field(default=None, ge=-1, le=10080)
