from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import ORIGIN, VALID_SETUP


def test_questions_are_exact_and_ordered(client: TestClient) -> None:
    data = client.get("/api/setup/questions").json()
    assert [q["text"] for q in data["questions"]] == [
        "あなたは誰ですか？",
        "あなたはどんな性格で嫌いなのか好きなのか自分について詳しく教えて下さい",
        "私の名前をどうしますか？",
    ]
    assert data["consent"]["purpose"]
    assert data["consent"]["stored_items"]


def test_status_before_and_after_setup(client: TestClient) -> None:
    assert client.get("/api/setup/status").json() == {"completed": False}
    assert client.post("/api/setup/complete", json=VALID_SETUP).status_code == 200
    assert client.get("/api/setup/status").json() == {"completed": True}


def test_setup_saves_profile_and_ai_name(setup_done: TestClient) -> None:
    profile = setup_done.get("/api/profile").json()
    assert [p["content"] for p in profile] == VALID_SETUP["answers"]
    assert all(p["source"] == "initial_setup" and p["confirmation_status"] == "confirmed" for p in profile)
    assert all(p["created_at"] and p["updated_at"] for p in profile)
    assert setup_done.get("/api/settings").json()["ai_name"] == "タニス"


def test_setup_requires_consent_and_saves_nothing(client: TestClient) -> None:
    response = client.post("/api/setup/complete", json={**VALID_SETUP, "consent": False})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "consent_required"
    assert client.get("/api/profile").json() == []
    assert client.get("/api/setup/status").json() == {"completed": False}


def test_setup_records_consent(setup_done: TestClient) -> None:
    db = setup_done.app.state.services.db
    with db.transaction() as conn:
        rows = conn.execute("SELECT kind, version, granted FROM consents").fetchall()
    assert [(r["kind"], r["granted"]) for r in rows] == [("initial_profile", 1)]


def test_setup_cannot_run_twice(setup_done: TestClient) -> None:
    response = setup_done.post("/api/setup/complete", json=VALID_SETUP)
    assert response.status_code == 409


def test_setup_rejects_empty_answer(client: TestClient) -> None:
    response = client.post("/api/setup/complete", json={**VALID_SETUP, "answers": ["a", "  ", "c"]})
    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "すべての質問に回答してください。"


def test_setup_rejects_bad_ai_name(client: TestClient) -> None:
    for name in ["", "a" * 33, "改行\nあり"]:
        response = client.post("/api/setup/complete", json={**VALID_SETUP, "ai_name": name})
        assert response.status_code == 422, name
        assert "message" in response.json()["detail"]


def test_setup_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/api/setup/complete", json={**VALID_SETUP, "extra": 1})
    assert response.status_code == 422


def test_failed_setup_is_rolled_back(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    services = client.app.state.services

    def boom(conn) -> None:  # noqa: ANN001
        raise RuntimeError("disk error")

    monkeypatch.setattr(services.settings, "mark_setup_completed", boom)
    raw = TestClient(client.app, raise_server_exceptions=False, headers={"Origin": ORIGIN})
    response = raw.post("/api/setup/complete", json=VALID_SETUP)
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "internal_error"
    assert client.get("/api/profile").json() == []
    assert client.get("/api/settings").json()["ai_name"] == ""
