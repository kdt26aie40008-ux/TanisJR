"""会話で予定を確かめる（復唱 → 通知の時間を聞く → 返事で実行・破棄）。カードのボタンでも決められる。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from tests.conftest import FakeOllama, sse_events


def at(days: int, hour: int) -> str:
    return (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=0).strftime("%Y-%m-%dT%H:%M")


def queue(fake: FakeOllama, *payloads: dict) -> None:
    """予定の下書き・返事の分類（形式指定の呼び出し）への応答を、呼ばれる順に用意する。"""
    fake.format_queue.extend(payloads)


def say(client: TestClient, *history: str) -> list[dict]:
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": t} for i, t in enumerate(history)]
    return sse_events(client.post("/api/chat", json={"messages": messages}).text)


def system_prompt(fake: FakeOllama) -> str:
    return [b for b in fake.paths("/api/chat") if "format" not in b][-1]["messages"][0]["content"]


def events_titles(client: TestClient) -> list[str]:
    return [e["summary"] for e in client.get("/api/calendar/events?days=7").json()]


def test_repeat_ask_reminder_then_yes_adds_with_reminder(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    client = setup_done
    queue(
        fake_ollama,
        {"action": "create", "summary": "歯医者", "start": at(1, 10)},
        {"decision": "yes", "reminder_minutes": 30},
    )

    first = say(client, "明日10時に歯医者の予定入れて")
    proposal = next(e for e in first if e["type"] == "calendar_proposal")["operation"]
    assert proposal["status"] == "pending"
    # 復唱して、通知の時間を聞くように指示している（まだ実行しない）
    prompt = system_prompt(fake_ollama)
    assert "歯医者" in prompt and "通知を何分前にするか聞く" in prompt and "まだ実行していない" in prompt
    assert events_titles(client) == []

    second = say(client, "明日10時に歯医者の予定入れて", "明日10時に歯医者を入れるね。通知は何分前がいい？", "30分前で")
    decided = next(e for e in second if e["type"] == "calendar_decided")["operation"]
    assert decided["status"] == "done" and decided["draft"]["reminder_minutes"] == 30
    assert events_titles(client) == ["歯医者"]
    assert client.get("/api/calendar/events?days=7").json()[0]["notify_minutes"] == 30
    assert "実行した" in system_prompt(fake_ollama)


def test_reminder_given_up_front_skips_the_question(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    queue(fake_ollama, {"action": "create", "summary": "会議", "start": at(1, 14), "reminder_minutes": 15})
    say(setup_done, "明日14時に会議の予定、15分前に通知して")
    prompt = system_prompt(fake_ollama)
    assert "通知: 15分前" in prompt and "これで進めてよいか" in prompt
    assert "通知を何分前にするか聞く" not in prompt


def test_no_discards(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    queue(fake_ollama, {"action": "create", "summary": "飲み会", "start": at(2, 19)}, {"decision": "no"})
    say(setup_done, "明後日19時に飲み会の予定入れて")
    events = say(setup_done, "明後日19時に飲み会の予定入れて", "入れていい？", "やっぱやめとく")
    assert next(e for e in events if e["type"] == "calendar_decided")["operation"]["status"] == "rejected"
    assert events_titles(setup_done) == []
    assert "やめた" in system_prompt(fake_ollama)


def test_unclear_reply_does_not_execute_and_asks_again(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    queue(fake_ollama, {"action": "create", "summary": "散髪", "start": at(1, 11)}, {"decision": "other"})
    say(setup_done, "明日11時に散髪の予定入れて")
    events = say(setup_done, "明日11時に散髪の予定入れて", "通知は何分前がいい？", "うーん、どうしよう")
    assert not any(e["type"] == "calendar_decided" for e in events)
    assert events_titles(setup_done) == []
    assert "返事待ち" in system_prompt(fake_ollama)
    # まだ確認中なので、ボタンでも決められる
    pending = setup_done.get("/api/calendar/operations").json()
    assert [op["draft"]["summary"] for op in pending] == ["散髪"]


def test_change_makes_a_new_draft(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    queue(
        fake_ollama,
        {"action": "create", "summary": "歯医者", "start": at(1, 15)},
        {"decision": "change"},
        # 直すのは確認中の下書きだけ（変える項目だけ返る）
        {"start": at(1, 16)},
    )
    say(setup_done, "明日15時に歯医者入れて")
    events = say(setup_done, "明日15時に歯医者入れて", "入れていい？", "4時にして")
    assert next(e for e in events if e["type"] == "calendar_decided")["operation"]["status"] == "rejected"
    new = next(e for e in events if e["type"] == "calendar_proposal")["operation"]
    assert new["draft"]["start"].endswith("16:00") and new["status"] == "pending"
    assert events_titles(setup_done) == []


def test_change_never_touches_other_events(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    """「直して」で、確認中の予定とは別の既存の予定を書き換えない（実機で起きた不具合の再発防止）。"""
    day = at(1, 10)
    existing = setup_done.post(
        "/api/calendar/operations",
        json={"action": "create", "draft": {"summary": "母校の文化祭", "start": day, "end": at(1, 11)}},
    ).json()["result_event_id"]
    queue(
        fake_ollama,
        {"action": "create", "summary": "美容院", "start": at(1, 15)},
        {"decision": "change"},
        {"start": at(1, 16)},
        {"decision": "yes"},
    )
    say(setup_done, "明日15時に美容院の予定入れて")
    say(setup_done, "明日15時に美容院の予定入れて", "入れていい？", "やっぱ16時にして")
    say(setup_done, "明日15時に美容院の予定入れて", "入れていい？", "やっぱ16時にして", "16時でいい？", "うん")
    events = {e["summary"]: e for e in setup_done.get("/api/calendar/events?days=7").json()}
    assert events["母校の文化祭"]["id"] == existing and events["母校の文化祭"]["start"].startswith(day)
    assert events["美容院"]["start"].endswith("16:00:00+09:00") or "T16:00" in events["美容院"]["start"]


def test_unrequested_reminder_is_ignored(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    # 通知のことを言っていないのに、モデルが通知を 0 分前で埋めても使わない（通知の時間を聞く）
    queue(fake_ollama, {"action": "create", "summary": "歯医者", "start": at(1, 10), "reminder_minutes": 0})
    op = next(e for e in say(setup_done, "明日10時に歯医者入れて") if e["type"] == "calendar_proposal")["operation"]
    assert op["draft"]["reminder_minutes"] is None
    assert "通知を何分前にするか聞く" in system_prompt(fake_ollama)


def test_change_start_only_keeps_length(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    # モデルが開始だけ動かして終了を元のまま返しても（16:00〜16:00）、元の長さを保って直す
    queue(
        fake_ollama,
        {"action": "create", "summary": "美容院", "start": at(1, 15)},
        {"decision": "change"},
        {"start": at(1, 16), "end": at(1, 16)},
    )
    say(setup_done, "明日15時に美容院入れて")
    events = say(setup_done, "明日15時に美容院入れて", "入れていい？", "やっぱ16時にして")
    new = next(e for e in events if e["type"] == "calendar_proposal")["operation"]["draft"]
    assert new["start"].endswith("16:00") and new["end"].endswith("17:00")


def test_reply_adjustments() -> None:
    """モデルの判定を、はっきりした言葉で補正する（実機で起きた取り違えの再発防止）。"""
    from app.calendar.conversation import _adjust, _Reply

    # 「16時にして」を了承と取り違えない
    assert _adjust(_Reply(decision="yes"), "やっぱ16時にして").decision == "change"
    assert _adjust(_Reply(decision="other"), "土曜じゃなくて日曜で").decision == "change"
    # 通知の時間を答えただけなら了承のまま
    r = _adjust(_Reply(decision="yes", reminder_minutes=60), "1時間前にして")
    assert r.decision == "yes" and r.reminder_minutes == 60
    # 通知のことを言っていなければ、モデルが埋めた通知の時間は使わない
    assert _adjust(_Reply(decision="yes", reminder_minutes=60), "うん").reminder_minutes is None
    # 「通知はいらない」は予定そのものの了承
    r = _adjust(_Reply(decision="no"), "通知はいらない")
    assert r.decision == "yes" and r.no_reminder
    # はっきり断っていれば断り
    assert _adjust(_Reply(decision="yes"), "やっぱやめとく").decision == "no"


def test_date_table_names_next_week() -> None:
    from datetime import date as _date

    from app.calendar.conversation import date_table

    table = date_table()
    today = datetime.now().date()
    next_monday = today + timedelta(days=7 - today.weekday())
    assert f"{next_monday.isoformat()}（月） " in table
    assert "来週月曜" in table.split(next_monday.isoformat())[1].splitlines()[0]
    assert isinstance(next_monday, _date)


def test_button_still_works(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    queue(fake_ollama, {"action": "create", "summary": "ジム", "start": at(1, 18)})
    op = next(e for e in say(setup_done, "明日18時にジムの予定入れて") if e["type"] == "calendar_proposal")["operation"]
    assert setup_done.post(f"/api/calendar/operations/{op['id']}/approve").json()["status"] == "done"
    assert events_titles(setup_done) == ["ジム"]
    # ボタンで決めたあとは、会話の返事で二重に実行しない
    events = say(setup_done, "明日18時にジムの予定入れて", "入れていい？", "うん")
    assert not any(e["type"] == "calendar_decided" for e in events)
    assert events_titles(setup_done) == ["ジム"]
