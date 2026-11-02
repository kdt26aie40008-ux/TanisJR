from __future__ import annotations

import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.calendar.models import EventDraft
from app.calendar.proposals import mentions_calendar, parse_proposal
from app.crypto import PREFIX
from tests.conftest import FakeGoogle, FakeOllama, sse_events

CLIENT_JSON = {"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-secret", "redirect_uris": ["http://localhost"]}}


def local(dt: datetime) -> str:
    return dt.astimezone().isoformat()


def tomorrow_at(hour: int) -> datetime:
    return (datetime.now() + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)


def connect(client: TestClient) -> None:
    assert client.post("/api/calendar/client", content=json.dumps(CLIENT_JSON)).status_code == 200
    url = client.post("/api/calendar/auth/start").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    page = client.get("/api/calendar/auth/callback", params={"state": state, "code": "auth-code"})
    assert "連携しました" in page.text, page.text


def raw_db(client: TestClient) -> bytes:
    path = client.app.state.services.db.path
    return b"".join(p.read_bytes() for p in path.parent.glob("twin.db*"))


# ---------- 連携 ----------


def test_client_json_validation(setup_done: TestClient) -> None:
    web = {"web": {"client_id": "x", "client_secret": "y"}}
    r = setup_done.post("/api/calendar/client", content=json.dumps(web))
    assert r.status_code == 400 and "デスクトップアプリ" in r.json()["detail"]["message"]
    assert setup_done.post("/api/calendar/client", content=b"not json").status_code == 400
    assert setup_done.get("/api/calendar/status").json()["configured"] is False


def test_oauth_flow_uses_pkce_and_minimal_scope(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    setup_done.post("/api/calendar/client", content=json.dumps(CLIENT_JSON))
    url = setup_done.post("/api/calendar/auth/start").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "accounts.google.com"
    assert q["scope"] == ["https://www.googleapis.com/auth/calendar.events"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8765/api/calendar/auth/callback"]
    setup_done.get("/api/calendar/auth/callback", params={"state": q["state"][0], "code": "c"})
    token_req = next(r for r in fake_google.requests if r["url"].endswith("/token"))
    assert "code_verifier=" in token_req["body"]
    assert setup_done.get("/api/calendar/status").json()["connected"] is True


def test_callback_rejects_unknown_state(setup_done: TestClient) -> None:
    setup_done.post("/api/calendar/client", content=json.dumps(CLIENT_JSON))
    page = setup_done.get("/api/calendar/auth/callback", params={"state": "forged", "code": "c"})
    assert "失敗" in page.text
    assert setup_done.get("/api/calendar/status").json()["connected"] is False


def test_secrets_are_encrypted(setup_done: TestClient) -> None:
    connect(setup_done)
    raw = raw_db(setup_done)
    assert b"GOCSPX-secret" not in raw and b"refresh-1" not in raw
    with setup_done.app.state.services.db.transaction() as conn:
        value = json.loads(conn.execute("SELECT value FROM settings WHERE key='google_token'").fetchone()[0])
    assert value.startswith(PREFIX)


def test_disconnect_revokes(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    setup_done.post("/api/calendar/disconnect")
    assert any(r["url"].endswith("/revoke") for r in fake_google.requests)
    assert setup_done.get("/api/calendar/status").json()["connected"] is False


def test_requires_connection(setup_done: TestClient) -> None:
    r = setup_done.get("/api/calendar/events")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "calendar_not_connected"


def test_revoked_token_asks_to_reconnect(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    fake_google.api_status = 401
    r = setup_done.get("/api/calendar/events")
    assert r.status_code == 401 and "連携し直して" in r.json()["detail"]["message"]
    assert setup_done.get("/api/calendar/status").json()["connected"] is False


def test_only_google_hosts_are_allowed() -> None:
    import asyncio

    from app.calendar.google import GoogleClient, GoogleError

    async def run() -> None:
        client = GoogleClient()
        try:
            with pytest.raises(GoogleError):
                await client._http.get("https://evil.example.com/steal")
        finally:
            await client.aclose()

    asyncio.run(run())


# ---------- 予定の取得と承認制の操作 ----------


def test_list_events(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    fake_google.add_event("歯医者", local(tomorrow_at(10)), local(tomorrow_at(11)), location="駅前")
    events = setup_done.get("/api/calendar/events").json()
    assert [(e["summary"], e["location"], e["all_day"]) for e in events] == [("歯医者", "駅前", False)]


def test_create_requires_explicit_approval(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    draft = {"summary": "勉強会", "start": tomorrow_at(14).strftime("%Y-%m-%dT%H:%M"), "end": tomorrow_at(15).strftime("%Y-%m-%dT%H:%M")}
    op = setup_done.post("/api/calendar/operations", json={"action": "create", "draft": draft}).json()
    assert op["status"] == "pending" and op["source"] == "user"
    # 承認前は Google に何も送られていない
    assert fake_google.events == {}
    done = setup_done.post(f"/api/calendar/operations/{op['id']}/approve").json()
    assert done["status"] == "done"
    assert [e["summary"] for e in fake_google.events.values()] == ["勉強会"]
    # 二重に承認しても1回だけ実行される
    assert setup_done.post(f"/api/calendar/operations/{op['id']}/approve").status_code == 409
    assert len(fake_google.events) == 1


def test_reject_does_nothing(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    event_id = fake_google.add_event("会議", local(tomorrow_at(9)), local(tomorrow_at(10)))
    op = setup_done.post("/api/calendar/operations", json={"action": "delete", "event_id": event_id}).json()
    assert op["target"]["summary"] == "会議"
    assert setup_done.post(f"/api/calendar/operations/{op['id']}/reject").json()["status"] == "rejected"
    assert event_id in fake_google.events
    assert setup_done.post(f"/api/calendar/operations/{op['id']}/approve").status_code == 409


def test_update_and_delete(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    event_id = fake_google.add_event("会議", local(tomorrow_at(9)), local(tomorrow_at(10)))
    draft = {"summary": "会議（変更）", "start": tomorrow_at(13).strftime("%Y-%m-%dT%H:%M"), "end": tomorrow_at(14).strftime("%Y-%m-%dT%H:%M"), "reminder_minutes": 30}
    op = setup_done.post("/api/calendar/operations", json={"action": "update", "event_id": event_id, "draft": draft}).json()
    setup_done.post(f"/api/calendar/operations/{op['id']}/approve")
    updated = fake_google.events[event_id]
    assert updated["summary"] == "会議（変更）"
    assert updated["reminders"]["overrides"][0]["minutes"] == 30
    # このアプリでの通知時刻も合わせて設定される
    assert setup_done.get("/api/calendar/events").json()[0]["notify_minutes"] == 30

    op = setup_done.post("/api/calendar/operations", json={"action": "delete", "event_id": event_id}).json()
    setup_done.post(f"/api/calendar/operations/{op['id']}/approve")
    assert fake_google.events == {}


def test_operation_on_missing_event(setup_done: TestClient) -> None:
    connect(setup_done)
    r = setup_done.post("/api/calendar/operations", json={"action": "delete", "event_id": "nope"})
    assert r.status_code == 404


def test_failed_execution_is_recorded(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    connect(setup_done)
    draft = {"summary": "x", "start": tomorrow_at(9).strftime("%Y-%m-%dT%H:%M"), "end": tomorrow_at(10).strftime("%Y-%m-%dT%H:%M")}
    op = setup_done.post("/api/calendar/operations", json={"action": "create", "draft": draft}).json()
    fake_google.api_status = 500
    assert setup_done.post(f"/api/calendar/operations/{op['id']}/approve").status_code == 502
    failed = setup_done.get("/api/calendar/operations", params={"status": "failed"}).json()
    assert failed[0]["id"] == op["id"] and failed[0]["error"]


@pytest.mark.parametrize(
    ("draft", "message"),
    [
        ({"summary": "x", "start": "2026-11-03T10:00", "end": "2026-11-03T09:00"}, "終了時刻"),
        ({"summary": " ", "start": "2026-11-03T10:00", "end": "2026-11-03T11:00"}, "タイトル"),
        ({"summary": "x", "start": "あした", "end": "2026-11-03T11:00"}, "開始日時"),
        ({"summary": "x", "start": "2026-13-45T10:00", "end": "2026-11-03T11:00"}, "形式"),
    ],
)
def test_draft_validation(setup_done: TestClient, draft: dict, message: str) -> None:
    connect(setup_done)
    r = setup_done.post("/api/calendar/operations", json={"action": "create", "draft": draft})
    assert r.status_code == 422 and message in r.json()["detail"]["message"]


def test_all_day_event_format() -> None:
    body = EventDraft(summary="旅行", all_day=True, start="2026-11-03", end="2026-11-04").to_google()
    assert body["start"] == {"date": "2026-11-03"}
    assert body["end"] == {"date": "2026-11-05"}  # Google は終了日を翌日で指定する


# ---------- AI の提案 ----------


def test_mentions_calendar() -> None:
    assert mentions_calendar("明日10時に歯医者の予定を入れて")
    assert mentions_calendar("会議をキャンセルして")
    assert not mentions_calendar("今日はいい天気だね")


def test_parse_proposal_rejects_unknown_event() -> None:
    raw = json.dumps({"action": "delete", "event_id": "made-up"})
    assert parse_proposal(raw, []) is None
    assert parse_proposal("not json", []) is None
    assert parse_proposal(json.dumps({"action": "none"}), []) is None


def test_ai_proposal_is_not_executed(setup_done: TestClient, fake_google: FakeGoogle, fake_ollama: FakeOllama) -> None:
    connect(setup_done)
    start = tomorrow_at(10).strftime("%Y-%m-%dT%H:%M")
    fake_ollama.extraction_raw = json.dumps({"action": "create", "summary": "歯医者", "start": start})
    events = sse_events(setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "明日10時に歯医者の予定を入れて"}]}).text)
    proposal = next(e for e in events if e["type"] == "calendar_proposal")["operation"]
    assert proposal["source"] == "ai" and proposal["status"] == "pending"
    assert proposal["draft"]["summary"] == "歯医者"
    assert proposal["draft"]["end"].endswith("11:00")  # 終了未指定は1時間後
    assert fake_google.events == {}  # AI の提案だけでは実行されない
    # 会話の文脈に「承認されるまで実行されない」ルールが入っている
    system = [b for b in fake_ollama.paths("/api/chat") if "format" not in b][-1]["messages"][0]["content"]
    assert "承認" in system and "追加しました" in system


def test_no_proposal_without_calendar_words(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    connect(setup_done)
    events = sse_events(setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "こんにちは"}]}).text)
    assert not any(e["type"] == "calendar_proposal" for e in events)
    assert not any("format" in b for b in fake_ollama.paths("/api/chat"))


def test_ai_proposals_can_be_disabled(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    connect(setup_done)
    setup_done.put("/api/settings", json={"calendar_ai_proposals": False})
    fake_ollama.extraction_raw = json.dumps({"action": "create", "summary": "x", "start": tomorrow_at(10).strftime("%Y-%m-%dT%H:%M")})
    events = sse_events(setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "予定を入れて"}]}).text)
    assert not any(e["type"] == "calendar_proposal" for e in events)
