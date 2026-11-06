"""アプリ内カレンダー（既定）。Google を使わず、この PC のこのユーザーのデータにだけ保存する。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.crypto import PREFIX
from tests.conftest import FakeGoogle, FakeOllama, sse_events


def at(days: int, hour: int) -> str:
    return (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=0).strftime("%Y-%m-%dT%H:%M")


def add(client: TestClient, summary: str, days: int = 1, hour: int = 10, **extra: object) -> dict:
    draft = {"summary": summary, "start": at(days, hour), "end": at(days, hour + 1), **extra}
    return client.post("/api/calendar/operations", json={"action": "create", "draft": draft}).json()


def raw_db(client: TestClient) -> bytes:
    path = client.app.state.services.db.path
    return b"".join(p.read_bytes() for p in path.parent.glob("twin.db*"))


def test_local_is_default_and_needs_no_google(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    status = setup_done.get("/api/calendar/status").json()
    assert status["backend"] == "local"
    op = add(setup_done, "歯医者", location="駅前")
    # 本人がフォームで確定した予定は、そのまま追加される
    assert op["status"] == "done" and op["source"] == "user"
    events = setup_done.get("/api/calendar/events").json()
    assert [(e["summary"], e["location"]) for e in events] == [("歯医者", "駅前")]
    # Google には何も送らない
    assert fake_google.events == {} and fake_google.requests == []


def test_contents_are_encrypted(setup_done: TestClient) -> None:
    add(setup_done, "秘密の面談", description="内容メモ")
    raw = raw_db(setup_done)
    assert "秘密の面談".encode() not in raw and "内容メモ".encode() not in raw
    with setup_done.app.state.services.db.transaction() as conn:
        assert conn.execute("SELECT data FROM local_events").fetchone()[0].startswith(PREFIX)


def test_update_delete_and_month_range(setup_done: TestClient) -> None:
    eid = add(setup_done, "会議")["result_event_id"]
    draft = {"summary": "会議（変更）", "start": at(1, 13), "end": at(1, 14), "reminder_minutes": 30}
    assert setup_done.post("/api/calendar/operations", json={"action": "update", "event_id": eid, "draft": draft}).json()["status"] == "done"
    event = setup_done.get("/api/calendar/events").json()[0]
    assert (event["summary"], event["notify_minutes"]) == ("会議（変更）", 30)

    # 月の表示用に、開始日を指定して取得できる
    later = add(setup_done, "来月の予定", days=40)["result_event_id"]
    start = (datetime.now() + timedelta(days=35)).date().isoformat()
    assert [e["id"] for e in setup_done.get(f"/api/calendar/events?start={start}&days=14").json()] == [later]

    assert setup_done.post("/api/calendar/operations", json={"action": "delete", "event_id": eid}).json()["status"] == "done"
    assert all(e["id"] != eid for e in setup_done.get("/api/calendar/events?days=60").json())
    # 存在しない予定は変更できない
    assert setup_done.post("/api/calendar/operations", json={"action": "delete", "event_id": eid}).status_code == 404


def test_all_day_event(setup_done: TestClient) -> None:
    day = (datetime.now() + timedelta(days=2)).date().isoformat()
    add(setup_done, "旅行", all_day=True, start=day, end=day)
    event = setup_done.get("/api/calendar/events").json()[0]
    assert (event["all_day"], event["start"], event["end"]) == (True, day, day)


def test_ai_proposals_still_need_approval(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction_raw = json.dumps({"action": "create", "summary": "歯医者", "start": at(1, 10)})
    response = setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "明日10時に歯医者の予定を入れて"}]})
    proposals = [e for e in sse_events(response.text) if e["type"] == "calendar_proposal"]
    assert len(proposals) == 1
    op = proposals[0]["operation"]
    assert (op["status"], op["source"]) == ("pending", "ai")
    # 承認するまでは追加されない
    assert setup_done.get("/api/calendar/events").json() == []
    setup_done.post(f"/api/calendar/operations/{op['id']}/approve")
    assert [e["summary"] for e in setup_done.get("/api/calendar/events").json()] == ["歯医者"]


def test_switching_to_google_hides_local_events(setup_done: TestClient) -> None:
    add(setup_done, "アプリ内の予定")
    setup_done.put("/api/settings", json={"calendar_backend": "google"})
    # Google 未連携なので予定は使えない（アプリ内の予定は消えずに残る）
    assert setup_done.get("/api/calendar/events").status_code == 409
    setup_done.put("/api/settings", json={"calendar_backend": "local"})
    assert [e["summary"] for e in setup_done.get("/api/calendar/events").json()] == ["アプリ内の予定"]
