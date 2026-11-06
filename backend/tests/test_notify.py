from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.calendar.models import CalendarEvent
from app.notify.scheduler import due_notifications, message_for
from tests.conftest import FakeGoogle, FakeNotifier
from tests.test_calendar import connect, google_backend  # noqa: F401  Google 連携として動かす（autouse）


def event(eid: str, start: datetime, minutes_long: int = 60, all_day: bool = False) -> CalendarEvent:
    if all_day:
        return CalendarEvent(id=eid, summary="終日", all_day=True, start=start.date().isoformat(), end=start.date().isoformat())
    return CalendarEvent(
        id=eid, summary=f"予定{eid}", all_day=False,
        start=start.astimezone().isoformat(), end=(start + timedelta(minutes=minutes_long)).astimezone().isoformat(),
    )


NOW = datetime(2026, 11, 2, 9, 50).astimezone()


def test_due_at_default_minutes() -> None:
    e = event("a", datetime(2026, 11, 2, 10, 0))
    assert due_notifications([e], {}, set(), NOW, 10)[0].event.id == "a"
    # まだ早い
    assert due_notifications([e], {}, set(), NOW - timedelta(minutes=1), 10) == []


def test_per_event_override_and_disable() -> None:
    e = event("a", datetime(2026, 11, 2, 10, 0))
    assert due_notifications([e], {"a": 30}, set(), NOW, 10) == []  # 30分前=9:20 は GRACE(15分)超過
    assert due_notifications([e], {"a": -1}, set(), NOW, 10) == []  # 通知しない
    assert len(due_notifications([e], {"a": 5}, set(), NOW + timedelta(minutes=5), 10)) == 1


def test_no_duplicates() -> None:
    e = event("a", datetime(2026, 11, 2, 10, 0))
    key = due_notifications([e], {}, set(), NOW, 10)[0].key
    assert due_notifications([e], {}, {key}, NOW + timedelta(minutes=1), 10) == []


def test_missed_while_off_within_grace_only() -> None:
    e = event("a", datetime(2026, 11, 2, 10, 0))
    # 9:50 に通知予定 → 10:04 に起動: 予定が始まっていても終了前で GRACE 内なので遅れて出す
    assert len(due_notifications([e], {}, set(), NOW + timedelta(minutes=14), 10)) == 1
    # 10:06 は GRACE(15分) を過ぎているので出さない
    assert due_notifications([e], {}, set(), NOW + timedelta(minutes=16), 10) == []


def test_all_day_notifies_in_the_morning() -> None:
    e = event("d", datetime(2026, 11, 2, 0, 0), all_day=True)
    assert len(due_notifications([e], {}, set(), datetime(2026, 11, 2, 8, 5).astimezone(), 10)) == 1
    assert due_notifications([e], {}, set(), datetime(2026, 11, 2, 7, 55).astimezone(), 10) == []


def test_message_text() -> None:
    e = event("a", datetime(2026, 11, 2, 10, 0)).model_copy(update={"location": "駅前"})
    item = due_notifications([e], {}, set(), NOW, 10)[0]
    title, body = message_for(item)
    assert title == "予定: 予定a"
    assert "10分後 10:00〜11:00" in body and "駅前" in body


def test_scheduler_end_to_end_survives_restart(setup_done: TestClient, fake_google: FakeGoogle, fake_notifier: FakeNotifier, make_client) -> None:  # noqa: ANN001
    connect(setup_done)
    start = (datetime.now() + timedelta(minutes=5)).replace(second=0, microsecond=0)
    fake_google.add_event("面談", start.astimezone().isoformat(), (start + timedelta(hours=1)).astimezone().isoformat())
    scheduler = setup_done.app.state.services.scheduler
    asyncio.run(scheduler.sync(force=True))
    # 予定のキャッシュは暗号化して保存される
    with setup_done.app.state.services.db.transaction() as conn:
        assert "面談" not in conn.execute("SELECT event FROM calendar_cache").fetchone()[0]
    due = asyncio.run(scheduler.run_once())
    assert len(due) == 1 and fake_notifier.shown[0][0] == "予定: 面談"
    # 再起動後（別インスタンス）も、送信済みは再通知せず、Google に繋がらなくてもキャッシュで判定できる
    fake_google.api_status = 500
    restarted = make_client()
    assert asyncio.run(restarted.app.state.services.scheduler.run_once()) == []
    assert len(fake_notifier.shown) == 1


def test_notifications_can_be_disabled(setup_done: TestClient, fake_google: FakeGoogle, fake_notifier: FakeNotifier) -> None:
    connect(setup_done)
    start = datetime.now() + timedelta(minutes=5)
    fake_google.add_event("x", start.astimezone().isoformat(), (start + timedelta(hours=1)).astimezone().isoformat())
    setup_done.put("/api/settings", json={"notifications_enabled": False})
    assert asyncio.run(setup_done.app.state.services.scheduler.run_once()) == []
    assert fake_notifier.shown == []


def test_set_event_notify(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    eid = fake_google.add_event("x", (datetime.now() + timedelta(days=1)).astimezone().isoformat(), (datetime.now() + timedelta(days=1, hours=1)).astimezone().isoformat())
    assert setup_done.put(f"/api/calendar/events/{eid}/notify", json={"minutes": -1}).status_code == 200
    assert setup_done.get("/api/calendar/events").json()[0]["notify_minutes"] == -1
    setup_done.put(f"/api/calendar/events/{eid}/notify", json={"minutes": None})
    assert setup_done.get("/api/calendar/events").json()[0]["notify_minutes"] is None
    assert setup_done.put("/api/calendar/events/..%2Fx/notify", json={"minutes": 5}).status_code in (404, 405, 422)


def test_test_notification(setup_done: TestClient, fake_notifier: FakeNotifier) -> None:
    assert setup_done.post("/api/calendar/notifications/test").json() == {"shown": True}
    assert fake_notifier.shown[0][0] == "通知のテスト"


def test_toast_script_does_not_embed_text() -> None:
    from app.notify.toast import _SCRIPT

    # 件名などの文字列はスクリプトに埋め込まず、環境変数で渡す（コマンド注入の防止）
    assert "$env:TWIN_TOAST_TITLE" in _SCRIPT and "SecurityElement]::Escape" in _SCRIPT
    assert _SCRIPT.isascii()
    json.dumps(_SCRIPT)
