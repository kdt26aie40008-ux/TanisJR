"""予定の通知スケジューラー。

- 状態（予定のキャッシュ・送信済み記録）は SQLite にあるため、再起動しても同じ判定を続けられる。
- 送信済みの記録で同じ通知を二重に出さない。
- PC が停止・スリープしている間は動けないため、その間の通知は出せない。
  起動直後に、通知時刻を過ぎてから GRACE 以内のものだけ遅れて1回出す。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.calendar.google import GoogleError
from app.calendar.models import CalendarEvent, local_now
from app.calendar.service import CalendarError, CalendarService
from app.db import Database, now_iso
from app.notify.toast import Notifier
from app.repositories.settings import SettingsRepository

logger = logging.getLogger(__name__)

GRACE = timedelta(minutes=15)
ALL_DAY_NOTIFY_AT = time(8, 0)
CHECK_INTERVAL_SECONDS = 30
SYNC_INTERVAL_SECONDS = 300


@dataclass(frozen=True)
class DueNotification:
    key: str
    event: CalendarEvent
    minutes: int
    notify_at: datetime


def notify_time(event: CalendarEvent, minutes: int) -> datetime:
    if event.all_day:
        # 終日予定は当日の朝に知らせる
        day = event.start_dt().date()
        return datetime.combine(day, ALL_DAY_NOTIFY_AT).astimezone()
    return event.start_dt() - timedelta(minutes=minutes)


def due_notifications(
    events: list[CalendarEvent],
    overrides: dict[str, int],
    sent: set[str],
    now: datetime,
    default_minutes: int,
) -> list[DueNotification]:
    due: list[DueNotification] = []
    for event in events:
        minutes = overrides.get(event.id, default_minutes)
        if minutes < 0:
            continue  # この予定は通知しない
        at = notify_time(event, minutes)
        key = f"{event.id}|{event.start}|{minutes if not event.all_day else 'allday'}"
        if key in sent:
            continue
        # 通知時刻を過ぎていて、遅れが GRACE 以内で、予定がまだ終わっていないもの
        if at <= now <= at + GRACE and now < event.end_dt():
            due.append(DueNotification(key, event, minutes, at))
    return due


def message_for(item: DueNotification) -> tuple[str, str]:
    e = item.event
    if e.all_day:
        when = "今日（終日）"
    else:
        start = e.start_dt()
        when = f"{start:%H:%M}〜{e.end_dt():%H:%M}"
        if item.minutes > 0:
            when = f"{item.minutes}分後 {when}"
    body = when + (f"\n場所: {e.location}" if e.location else "")
    return f"予定: {e.summary}", body


class NotificationScheduler:
    def __init__(
        self, db: Database, settings: SettingsRepository, calendar: CalendarService, notifier: Notifier
    ) -> None:
        self.db = db
        self.settings = settings
        self.calendar = calendar
        self.notifier = notifier
        self._last_sync = 0.0
        self.last_error: str | None = None
        self.last_sync_at: str | None = None

    def sent_keys(self) -> set[str]:
        with self.db.transaction() as conn:
            return {r["key"] for r in conn.execute("SELECT key FROM notifications_sent")}

    def _mark_sent(self, key: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO notifications_sent (key, sent_at) VALUES (?, ?)", (key, now_iso()))

    def _cleanup(self) -> None:
        cutoff = (datetime.now().astimezone() - timedelta(days=14)).isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM notifications_sent WHERE sent_at < ?", (cutoff,))

    async def sync(self, force: bool = False) -> None:
        loop_time = asyncio.get_running_loop().time()
        if not force and loop_time - self._last_sync < SYNC_INTERVAL_SECONDS:
            return
        self._last_sync = loop_time
        if not self.calendar.is_connected():
            return
        try:
            await self.calendar.sync_cache()
            self.last_error = None
            self.last_sync_at = now_iso()
        except (GoogleError, CalendarError) as exc:
            # 通信できない間もキャッシュ済みの予定で通知を続ける
            self.last_error = exc.message
            logger.warning("Calendar sync failed (%s)", exc.code)

    async def run_once(self, now: datetime | None = None) -> list[DueNotification]:
        settings = self.settings.get()
        if not settings.notifications_enabled:
            return []
        await self.sync()
        due = due_notifications(
            self.calendar.cached_events(),
            self.calendar.notify_overrides(),
            self.sent_keys(),
            now or local_now(),
            settings.default_reminder_minutes,
        )
        for item in due:
            # 先に記録してから通知する（通知処理が途中で落ちても二重に出さない）
            self._mark_sent(item.key)
            title, body = message_for(item)
            await self.notifier.notify(title, body)
        return due

    async def run_forever(self) -> None:
        self._cleanup()
        while True:
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001  スケジューラーは止めない
                logger.error("Notification scheduler error: %s", type(exc).__name__)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
