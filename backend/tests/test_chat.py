from __future__ import annotations

import logging

import httpx
from fastapi.testclient import TestClient

from tests.conftest import FakeOllama, ndjson, sse_events

USER_MSG = {"messages": [{"role": "user", "content": "今日なにしよう"}]}


def test_chat_requires_setup(client: TestClient) -> None:
    response = client.post("/api/chat", json=USER_MSG)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "setup_required"


def test_chat_streams_tokens(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    response = setup_done.post("/api/chat", json=USER_MSG)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    assert events[0] == {"type": "token", "content": "こんにちは"}
    assert events[-1] == {"type": "done", "model": "qwen3:8b"}


def test_chat_sends_persona_with_profile(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    setup_done.post("/api/chat", json=USER_MSG)
    body = next(r["body"] for r in fake_ollama.requests if r["path"] == "/api/chat")
    system = body["messages"][0]
    assert system["role"] == "system"
    assert "タニス" in system["content"]
    assert "山田太郎" in system["content"]
    assert "反論" in system["content"]
    assert body["messages"][-1] == {"role": "user", "content": "今日なにしよう"}
    assert body["model"] == "qwen3:8b"
    assert body["think"] is False


def test_chat_validates_input(setup_done: TestClient) -> None:
    bad = [
        {"messages": []},
        {"messages": [{"role": "system", "content": "x"}]},
        {"messages": [{"role": "user", "content": "x" * 8001}]},
        {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]},
    ]
    for body in bad:
        assert setup_done.post("/api/chat", json=body).status_code == 422, body


def test_chat_falls_back_on_oom(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    def handler(body: dict) -> httpx.Response:
        if body["options"].get("num_gpu") == 0:
            return ndjson([{"message": {"content": "CPUで回答"}, "done": True}])
        return httpx.Response(500, json={"error": "CUDA error: out of memory"})

    fake_ollama.chat_handler = handler
    events = sse_events(setup_done.post("/api/chat", json=USER_MSG).text)
    types = [e["type"] for e in events]
    assert types.count("notice") == 2  # コンテキスト縮小 → CPU
    assert {"type": "token", "content": "CPUで回答"} in events
    assert events[-1]["type"] == "done"


def test_chat_reports_error_when_all_fallbacks_fail(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.chat_handler = lambda body: httpx.Response(500, json={"error": "out of memory"})
    events = sse_events(setup_done.post("/api/chat", json=USER_MSG).text)
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "out_of_memory"
    assert "不足" in events[-1]["message"]


def test_chat_model_not_found(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.chat_handler = lambda body: httpx.Response(404, json={"error": "model 'qwen3:8b' not found"})
    events = sse_events(setup_done.post("/api/chat", json=USER_MSG).text)
    assert events == [
        {"type": "error", "code": "model_not_found", "message": events[0]["message"]},
    ]
    assert "ダウンロード" in events[0]["message"]


def test_chat_ollama_down(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    def handler(body: dict) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fake_ollama.chat_handler = handler
    events = sse_events(setup_done.post("/api/chat", json=USER_MSG).text)
    assert events[-1]["code"] == "ollama_unavailable"


def test_chat_content_is_not_logged(setup_done: TestClient, fake_ollama: FakeOllama, caplog) -> None:  # noqa: ANN001
    fake_ollama.chat_handler = lambda body: httpx.Response(500, json={"error": "boom"})
    with caplog.at_level(logging.DEBUG):
        setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "秘密の相談ABC123"}]})
    assert "秘密の相談ABC123" not in caplog.text


def test_chat_is_not_persisted(setup_done: TestClient) -> None:
    setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "保存されないはずZZZ"}]})
    db_path = setup_done.app.state.services.config.db_path
    raw = b"".join(p.read_bytes() for p in db_path.parent.glob("twin.db*"))
    assert "保存されないはずZZZ".encode() not in raw
