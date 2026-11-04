"""AI から話しかける（朝のあいさつ・予定の前・しばらく話していないとき）。

アプリの画面が開いている間に画面側から定期的に問い合わせ、話しかける内容があればここで作る。
同じことを何度も言わないよう、話しかけた記録（種類と日付・予定IDだけ。本文は保存しない）を残す。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.calendar.models import CalendarEvent, local_now, to_local
from app.db import Database, now_iso
from app.schemas import AppSettings

logger = logging.getLogger(__name__)

# 朝のあいさつをする時間帯の終わり（これ以降はその日のあいさつをしない）
MORNING_UNTIL = time(11, 0)


@dataclass(frozen=True)
class Occasion:
    kind: str  # morning | event | idle
    key: str  # 重複を防ぐための記録キー
    situation: str  # AI に伝える状況


def _parse_hm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    """話しかけない時間帯か（23:00〜07:00 のように日付をまたぐ指定にも対応）。"""
    s, e, t = _parse_hm(start), _parse_hm(end), now.time()
    if s == e:
        return False
    return s <= t < e if s < e else t >= s or t < e


def _event_start(event: CalendarEvent) -> datetime | None:
    if event.all_day:
        return None
    try:
        return to_local(event.start)
    except ValueError:
        return None


def find_occasion(
    settings: AppSettings,
    now: datetime,
    events: list[CalendarEvent],
    idle_minutes: int | None,
    already_sent: set[str],
    last_idle_at: datetime | None,
) -> Occasion | None:
    """いま話しかけるきっかけがあれば返す。優先度: 予定の前 > 朝のあいさつ > しばらく話していない。"""
    if not settings.proactive_enabled or in_quiet_hours(now, settings.quiet_start, settings.quiet_end):
        return None

    if settings.proactive_event_minutes:
        for event in events:
            start = _event_start(event)
            if start is None:
                continue
            left = (start - now).total_seconds() / 60
            key = f"proactive:event:{event.id}:{event.start}"
            if 0 <= left <= settings.proactive_event_minutes and key not in already_sent:
                return Occasion(
                    "event", key, f"もうすぐ予定「{event.summary}」があります（{start:%H:%M} から、あと約{round(left)}分）。"
                )

    today = now.date().isoformat()
    morning_key = f"proactive:morning:{today}"
    if settings.proactive_morning and morning_key not in already_sent and now.time() < MORNING_UNTIL:
        todays = [
            f"{s:%H:%M} {e.summary}" if (s := _event_start(e)) else f"終日 {e.summary}"
            for e in events
            if (e.start[:10] == today)
        ]
        plan = f"今日の予定: {'、'.join(todays)}。" if todays else "今日の予定は登録されていません。"
        return Occasion("morning", morning_key, f"朝です。今日はじめて顔を合わせました。{plan}")

    if settings.proactive_idle_hours and idle_minutes is not None and idle_minutes >= settings.proactive_idle_hours * 60:
        if last_idle_at is None or now - last_idle_at >= timedelta(hours=settings.proactive_idle_hours):
            hours = idle_minutes // 60
            return Occasion("idle", "proactive:idle:last", f"{hours}時間ほど話していません。")
    return None


INSTRUCTION = """\
（これはユーザーの発言ではなく、アプリからの指示です）
いまの状況: {situation}
あなたから{user}に、自然に話しかけてください。
- 1〜2文の短いひと言にする。説明や前置きはしない。
- 予定の話なら、時刻と内容に触れて、準備ができているか気にかける。
- 押しつけがましくせず、返事をしたくなるような軽い問いかけで終えてもよい。
- 話しかける文だけを書く。"""


def build_instruction(occasion: Occasion, user_name: str) -> str:
    return INSTRUCTION.format(situation=occasion.situation, user=f"{user_name}さん" if user_name else "ユーザー")


class ProactiveLog:
    """話しかけた記録。通知の送信記録と同じ表を使う（キーの先頭で区別する）。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def sent_keys(self) -> set[str]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT key FROM notifications_sent WHERE key LIKE 'proactive:%'").fetchall()
        return {r["key"] for r in rows}

    def last_idle_at(self) -> datetime | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT sent_at FROM notifications_sent WHERE key = 'proactive:idle:last'").fetchone()
        return datetime.fromisoformat(row["sent_at"]).astimezone() if row else None

    def mark(self, key: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO notifications_sent (key, sent_at) VALUES (?, ?)", (key, now_iso()))


def now() -> datetime:
    return local_now()
