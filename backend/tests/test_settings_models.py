from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FakeOllama, sse_events


def test_default_settings(client: TestClient) -> None:
    data = client.get("/api/settings").json()
    assert data["model"] == "qwen3:8b"
    assert data["think"] is False


def test_update_settings_partial(setup_done: TestClient) -> None:
    data = setup_done.put("/api/settings", json={"temperature": 0.3, "ai_name": "エフ"}).json()
    assert data["temperature"] == 0.3
    assert data["ai_name"] == "エフ"
    assert setup_done.get("/api/settings").json()["temperature"] == 0.3


def test_voice_turn_settings(setup_done: TestClient) -> None:
    data = setup_done.get("/api/settings").json()
    # 既定: 黙ったら自動で送る（1.2秒）、続けて聞き取るのはオフ
    assert (data["voice_auto_stop"], data["voice_silence_ms"], data["voice_handsfree"]) == (True, 1200, False)
    data = setup_done.put("/api/settings", json={"voice_silence_ms": 800, "voice_handsfree": True}).json()
    assert (data["voice_silence_ms"], data["voice_handsfree"]) == (800, True)


def test_behavior_settings(setup_done: TestClient) -> None:
    data = setup_done.get("/api/settings").json()
    behavior = {k: v for k, v in data.items() if k.startswith("behavior_")}
    # 割り込みだけはマイクがスピーカーの音を拾うおそれがあるため既定でオフ
    assert behavior == {
        "behavior_nod": True,
        "behavior_gaze": True,
        "behavior_backchannel": True,
        "behavior_barge_in": False,
        "behavior_sentence_emotion": True,
    }
    data = setup_done.put("/api/settings", json={"behavior_nod": False, "behavior_barge_in": True}).json()
    assert (data["behavior_nod"], data["behavior_barge_in"]) == (False, True)


def test_update_settings_validation(setup_done: TestClient) -> None:
    for body in [{"temperature": 5}, {"model": "bad model!"}, {"num_ctx": 10}, {}, {"unknown": 1}, {"voice_silence_ms": 100}]:
        response = setup_done.put("/api/settings", json=body)
        assert response.status_code in (400, 422), body
        assert response.json()["detail"]["message"]


def test_update_profile(setup_done: TestClient) -> None:
    response = setup_done.put("/api/profile", json={"key": "setup.q1_identity", "content": "更新後"})
    assert response.status_code == 200
    entry = response.json()
    assert entry["content"] == "更新後"
    assert entry["source"] == "user_edit"


def test_update_profile_unknown_key(setup_done: TestClient) -> None:
    assert setup_done.put("/api/profile", json={"key": "nope", "content": "x"}).status_code == 404


def test_models_status(client: TestClient) -> None:
    data = client.get("/api/models/status").json()
    assert data["ollama_available"] is True
    assert data["configured_model_installed"] is True
    assert any(m["name"] == "qwen3:8b" for m in data["catalog"])
    assert data["storage_path"]


def test_models_status_missing_model(client: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.models = []
    assert client.get("/api/models/status").json()["configured_model_installed"] is False


def test_pull_requires_confirmation(client: TestClient, fake_ollama: FakeOllama) -> None:
    response = client.post("/api/models/pull", json={"model": "qwen3:4b", "confirmed": False})
    assert response.status_code == 400
    assert not any(r["path"] == "/api/pull" for r in fake_ollama.requests)


def test_pull_only_catalog_models(client: TestClient) -> None:
    response = client.post("/api/models/pull", json={"model": "someone/malware:latest", "confirmed": True})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "model_not_allowed"


def test_pull_streams_progress(client: TestClient) -> None:
    events = sse_events(client.post("/api/models/pull", json={"model": "qwen3:4b", "confirmed": True}).text)
    assert events[0]["type"] == "progress"
    assert events[-1] == {"type": "done", "model": "qwen3:4b"}


def test_health(client: TestClient) -> None:
    data = client.get("/api/health").json()
    assert data["ollama"]["available"] is True
