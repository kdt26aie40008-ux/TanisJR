from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.calendar.models import CalendarEvent
from app.schemas import AppSettings
from app.services.proactive import find_occasion, in_quiet_hours

JST = timezone(timedelta(hours=9))


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 4, hour, minute, tzinfo=JST)


def event(start: datetime, summary: str = "打ち合わせ", eid: str = "e1") -> CalendarEvent:
    return CalendarEvent(
        id=eid, summary=summary, all_day=False, start=start.isoformat(), end=(start + timedelta(hours=1)).isoformat()
    )


ON = AppSettings(proactive_enabled=True)


def test_quiet_hours_across_midnight() -> None:
    assert in_quiet_hours(at(23, 30), "23:00", "07:00")
    assert in_quiet_hours(at(6, 59), "23:00", "07:00")
    assert not in_quiet_hours(at(7, 0), "23:00", "07:00")
    assert in_quiet_hours(at(13), "12:00", "14:00")
    assert not in_quiet_hours(at(15), "12:00", "14:00")


def test_nothing_when_disabled_or_quiet() -> None:
    assert find_occasion(AppSettings(), at(8), [], None, set(), None) is None
    assert find_occasion(ON, at(6), [], None, set(), None) is None


def test_event_has_priority_and_is_said_once() -> None:
    soon = event(at(9, 10))
    occasion = find_occasion(ON, at(9), [soon], None, set(), None)
    assert occasion is not None and occasion.kind == "event"
    assert "打ち合わせ" in occasion.situation and "09:10" in occasion.situation
    # 一度話しかけた予定は、次は朝のあいさつに回る
    again = find_occasion(ON, at(9, 1), [soon], None, {occasion.key}, None)
    assert again is not None and again.kind == "morning"
    # 予定がまだ先なら声をかけない
    later = find_occasion(ON, at(9), [event(at(10))], None, {"proactive:morning:2026-11-04"}, None)
    assert later is None


def test_morning_greeting_mentions_todays_plan_once() -> None:
    occasion = find_occasion(ON, at(8), [event(at(15), "歯医者")], None, set(), None)
    assert occasion is not None and occasion.kind == "morning"
    assert "15:00 歯医者" in occasion.situation
    assert find_occasion(ON, at(8, 5), [], None, {occasion.key}, None) is None
    # 昼以降はあいさつしない
    assert find_occasion(ON, at(12), [], None, set(), None) is None


def test_idle_check_in() -> None:
    sent = {"proactive:morning:2026-11-04"}
    assert find_occasion(ON, at(15), [], 60, sent, None) is None
    occasion = find_occasion(ON, at(15), [], 200, sent, None)
    assert occasion is not None and occasion.kind == "idle"
    # 前回の声かけから設定時間がたつまでは繰り返さない
    assert find_occasion(ON, at(15), [], 400, sent, at(14)) is None
    assert find_occasion(AppSettings(proactive_enabled=True, proactive_idle_hours=0), at(15), [], 400, sent, None) is None


def test_proactive_endpoint_generates_and_records(setup_done: TestClient, fake_ollama, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("app.services.proactive.now", lambda: at(8))
    assert setup_done.post("/api/proactive/next", json={}).json() == {"kind": None}  # 既定はオフ

    setup_done.put("/api/settings", json={"proactive_enabled": True})
    first = setup_done.post("/api/proactive/next", json={"idle_minutes": 0}).json()
    assert first == {"kind": "morning", "text": "教師の回答です"}
    instruction = fake_ollama.paths("/api/chat")[-1]["messages"][-1]["content"]
    assert "アプリからの指示" in instruction and "朝です" in instruction
    # 同じ朝に2回はあいさつしない
    assert setup_done.post("/api/proactive/next", json={"idle_minutes": 0}).json() == {"kind": None}


def test_wake_requires_profile_and_consent(setup_done: TestClient) -> None:
    status = setup_done.get("/api/wake/status").json()
    assert status["enabled"] is False and status["ready"] is False
    assert set(status["missing"]) == {"呼んでほしい名前", "あなたの個性（性格・価値観・好き嫌い）", "あなたの特徴（口ぐせ・話し方・生活のリズムなど）"}
    response = setup_done.post("/api/wake", json={"enabled": True, "consent": True})
    assert response.status_code == 409
    assert "あなたのこと" in response.json()["detail"]["message"]

    for key, content in [("self.user_name", "たろう"), ("self.personality", "負けず嫌い"), ("self.traits", "早口")]:
        assert setup_done.put("/api/profile", json={"key": key, "content": content}).status_code == 200
    # 入力した内容は「あなたのこと」として AI に伝わる（初回の3問はそのまま残る）
    keys = [e["key"] for e in setup_done.get("/api/profile").json()]
    assert keys[:3] == ["setup.q1_identity", "setup.q2_personality", "setup.q3_ai_name"]
    assert "self.user_name" in keys

    assert setup_done.get("/api/wake/status").json()["ready"] is True
    assert setup_done.post("/api/wake", json={"enabled": True}).status_code == 400  # 同意なし
    assert setup_done.post("/api/wake", json={"enabled": True, "consent": True}).json()["enabled"] is True
    assert setup_done.get("/api/settings").json()["wake_enabled"] is True
    # 通常の設定変更ではオンにできない
    assert setup_done.put("/api/settings", json={"wake_enabled": True}).status_code == 422
    assert setup_done.post("/api/wake", json={"enabled": False}).json()["enabled"] is False


def test_language_reaches_prompt_and_stt(setup_done: TestClient, fake_ollama, fake_stt) -> None:  # noqa: ANN001
    setup_done.put("/api/settings", json={"language": "en"})
    setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    system = fake_ollama.paths("/api/chat")[-1]["messages"][0]["content"]
    assert "英語で、簡潔かつ自然に話す。" in system
    setup_done.post("/api/speech/stt?fast=true", content=b"x" * 100, headers={"Content-Type": "audio/webm"})
    assert fake_stt.options[-1] == ("en", True)
    assert setup_done.put("/api/settings", json={"language": "xx"}).status_code == 422


@pytest.mark.parametrize("value", ["24:00", "7:00", "aa:bb"])
def test_quiet_hours_validation(setup_done: TestClient, value: str) -> None:
    assert setup_done.put("/api/settings", json={"quiet_start": value}).status_code == 422
