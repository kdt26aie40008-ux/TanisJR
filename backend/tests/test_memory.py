from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.crypto import PREFIX
from tests.conftest import FakeOllama, sse_events

EMBED = "qwen3-embedding:0.6b"


def create_conversation(client: TestClient, messages: list[dict] | None = None) -> str:
    response = client.post("/api/conversations", json={"messages": messages or []})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def chat(client: TestClient, text: str, conversation_id: str | None = None, history: list[dict] | None = None) -> list[dict]:
    body: dict = {"messages": [*(history or []), {"role": "user", "content": text}]}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = client.post("/api/chat", json=body)
    assert response.status_code == 200, response.text
    return sse_events(response.text)


def index_ids(client: TestClient) -> set[str]:
    return client.app.state.services.index.ids(EMBED)


def raw_db(client: TestClient) -> bytes:
    path = client.app.state.services.db.path
    return b"".join(p.read_bytes() for p in path.parent.glob("twin.db*"))


# ---------- 会話の保存選択 ----------


def test_unsaved_chat_leaves_no_trace(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction = [{"content": "ユーザーは猫が好き", "category": "preference", "importance": 5, "sensitive": False}]
    chat(setup_done, "保存しない猫の話XYZ")
    assert setup_done.get("/api/conversations").json() == []
    assert setup_done.get("/api/memories").json() == []
    # 記憶抽出は呼ばれていない
    assert not any("format" in b for b in fake_ollama.paths("/api/chat"))
    assert "保存しない猫の話XYZ".encode() not in raw_db(setup_done)


def test_saved_chat_persists_turn_encrypted(setup_done: TestClient) -> None:
    cid = create_conversation(setup_done, [{"role": "user", "content": "前の発言"}, {"role": "assistant", "content": "前の返答"}])
    events = chat(setup_done, "保存する発言ABC", cid)
    assert {"type": "saved", "conversation_id": cid} in events
    detail = setup_done.get(f"/api/conversations/{cid}").json()
    assert [m["content"] for m in detail["messages"]] == ["前の発言", "前の返答", "保存する発言ABC", "こんにちは"]
    assert detail["title"] == "前の発言"
    assert "保存する発言ABC".encode() not in raw_db(setup_done)
    with setup_done.app.state.services.db.transaction() as conn:
        assert all(r[0].startswith(PREFIX) for r in conn.execute("SELECT content FROM messages"))


def test_failed_turn_is_not_saved(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    import httpx

    cid = create_conversation(setup_done)
    fake_ollama.chat_handler = lambda body: httpx.Response(500, json={"error": "boom"})
    events = chat(setup_done, "失敗する発言", cid)
    assert events[-1]["type"] == "error"
    assert setup_done.get(f"/api/conversations/{cid}").json()["messages"] == []


def test_chat_with_unknown_conversation(setup_done: TestClient) -> None:
    response = setup_done.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "x"}], "conversation_id": "0" * 32}
    )
    assert response.status_code == 404


def test_conversation_id_is_validated(setup_done: TestClient) -> None:
    response = setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "x"}], "conversation_id": "../x"})
    assert response.status_code == 422


# ---------- 記憶の抽出 ----------


def test_general_memory_is_auto_saved_and_indexed(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction = [{"content": "ユーザーはラーメンが好き", "category": "preference", "importance": 5, "sensitive": False}]
    cid = create_conversation(setup_done)
    chat(setup_done, "ラーメンが大好きなんだ", cid)
    memories = setup_done.get("/api/memories").json()
    assert len(memories) == 1
    m = memories[0]
    assert (m["status"], m["confirmation_status"], m["sensitivity"]) == ("active", "auto", "general")
    assert m["source_type"] == "conversation"
    assert m["source_conversation_id"] == cid
    assert m["source_excerpt"] == "ラーメンが大好きなんだ"
    assert m["created_at"] and m["updated_at"]
    assert m["indexed"] is True
    assert index_ids(setup_done) == {m["id"]}


@pytest.mark.parametrize(
    "candidate",
    [
        {"content": "ユーザーは東京に住んでいる", "category": "personal", "importance": 6, "sensitive": False},
        {"content": "ユーザーは慎重な性格", "category": "personality", "importance": 5, "sensitive": False},
        {"content": "ユーザーは誠実さを大切にする", "category": "values", "importance": 5, "sensitive": False},
        {"content": "ユーザーは持病がある", "category": "fact", "importance": 5, "sensitive": True},
        # LLM が分類を誤っても、居住地などのキーワードがあれば承認待ちにする
        {"content": "ユーザーは神戸に住んでいる", "category": "fact", "importance": 7, "sensitive": False},
        {"content": "ユーザーは妻と二人暮らし", "category": "other", "importance": 5, "sensitive": False},
    ],
)
def test_important_memory_waits_for_approval(setup_done: TestClient, fake_ollama: FakeOllama, candidate: dict) -> None:
    fake_ollama.extraction = [candidate]
    chat(setup_done, "発言", create_conversation(setup_done))
    pending = setup_done.get("/api/memories?status=pending").json()
    assert [p["content"] for p in pending] == [candidate["content"]]
    assert pending[0]["sensitivity"] == "important"
    assert pending[0]["confirmation_status"] == "pending"
    # 承認前は索引に入らない（RAG に使われない）
    assert index_ids(setup_done) == set()


def test_high_importance_alone_is_not_sensitive(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction = [{"content": "ユーザーは毎朝コーヒーを飲む", "category": "habit", "importance": 9, "sensitive": False}]
    chat(setup_done, "毎朝コーヒー", create_conversation(setup_done))
    assert setup_done.get("/api/memories?status=active").json()[0]["content"] == "ユーザーは毎朝コーヒーを飲む"


def test_auto_extract_can_be_disabled(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    setup_done.put("/api/settings", json={"auto_extract": False})
    fake_ollama.extraction = [{"content": "ユーザーは猫が好き", "category": "preference", "importance": 5, "sensitive": False}]
    chat(setup_done, "猫が好き", create_conversation(setup_done))
    assert setup_done.get("/api/memories").json() == []


def test_duplicates_are_skipped(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    cid = create_conversation(setup_done)
    fake_ollama.extraction = [{"content": "ユーザーはラーメンが好き", "category": "preference", "importance": 5, "sensitive": False}]
    chat(setup_done, "ラーメン", cid)
    # 表記ゆれ（同一）とベクトルが近いもの
    fake_ollama.extraction = [
        {"content": "ユーザーは ラーメンが好き。", "category": "preference", "importance": 5, "sensitive": False},
        {"content": "ユーザーはラーメンを好む", "category": "preference", "importance": 5, "sensitive": False},
    ]
    chat(setup_done, "ラーメン", cid)
    assert len(setup_done.get("/api/memories").json()) == 1


def test_invalid_extraction_output_is_ignored(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction_raw = "これはJSONではありません"
    events = chat(setup_done, "何か", create_conversation(setup_done))
    assert events[-1]["type"] == "done"
    assert setup_done.get("/api/memories").json() == []


def test_extraction_only_uses_user_message(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    cid = create_conversation(setup_done)
    history = [{"role": "user", "content": "質問"}, {"role": "assistant", "content": "好きな食べ物は？"}]
    chat(setup_done, "ラーメン", cid, history)
    request = next(b for b in fake_ollama.paths("/api/chat") if "format" in b)
    prompt = request["messages"][1]["content"]
    assert "<user>\nラーメン\n</user>" in prompt
    assert "好きな食べ物は？" in prompt and "ここからは抽出しない" in prompt


# ---------- RAG ----------


def add_memory(client: TestClient, content: str, category: str = "preference") -> dict:
    response = client.post("/api/memories", json={"content": content, "category": category, "importance": 5})
    assert response.status_code == 200, response.text
    return response.json()


def system_prompt_of_last_chat(fake_ollama: FakeOllama) -> str:
    return [b for b in fake_ollama.paths("/api/chat") if "format" not in b][-1]["messages"][0]["content"]


def test_rag_includes_only_relevant_memories(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    ramen = add_memory(setup_done, "ユーザーはラーメンが好き")
    add_memory(setup_done, "ユーザーは犬を飼っている")
    events = chat(setup_done, "今日の昼はラーメンにしようかな")
    prompt = system_prompt_of_last_chat(fake_ollama)
    assert "ユーザーはラーメンが好き" in prompt
    assert "犬を飼っている" not in prompt
    used = next(e for e in events if e["type"] == "memories_used")
    assert [i["id"] for i in used["items"]] == [ramen["id"]]


def test_rag_with_no_memories_adds_nothing(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    events = chat(setup_done, "ラーメン")
    assert not any(e["type"] == "memories_used" for e in events)
    assert "関連する記憶" not in system_prompt_of_last_chat(fake_ollama)
    # 索引が空なら埋め込みも呼ばない
    assert fake_ollama.paths("/api/embed") == []


def test_rag_respects_max_results(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    for i in range(4):
        add_memory(setup_done, f"ユーザーはラーメン{i}号店が好き")
    setup_done.put("/api/settings", json={"rag_max_results": 2})
    events = chat(setup_done, "ラーメン")
    assert len(next(e for e in events if e["type"] == "memories_used")["items"]) == 2


def test_pending_memory_is_not_used_until_approved(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction = [{"content": "ユーザーは東京のラーメン屋で働いている", "category": "personal", "importance": 6, "sensitive": True}]
    chat(setup_done, "東京のラーメン屋で働いてる", create_conversation(setup_done))
    pending_id = setup_done.get("/api/memories?status=pending").json()[0]["id"]
    chat(setup_done, "ラーメン")
    assert "ラーメン屋で働いている" not in system_prompt_of_last_chat(fake_ollama)

    approved = setup_done.post(f"/api/memories/{pending_id}/approve").json()
    assert (approved["status"], approved["confirmation_status"]) == ("active", "confirmed")
    chat(setup_done, "ラーメン")
    assert "ラーメン屋で働いている" in system_prompt_of_last_chat(fake_ollama)


def test_embedding_unavailable_keeps_memory_and_notifies(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.embed_available = False
    memory = add_memory(setup_done, "ユーザーはラーメンが好き")
    assert memory["indexed"] is False
    events = chat(setup_done, "ラーメン")
    assert any(e["type"] == "notice" and "記憶" in e["message"] for e in events)
    assert events[-1]["type"] == "done"
    # モデルが使えるようになったら再インデックスで反映される
    fake_ollama.embed_available = True
    assert setup_done.post("/api/memories/reindex").json()["indexed"] == 1
    assert index_ids(setup_done) == {memory["id"]}


# ---------- 記憶管理 ----------


def test_search_and_filter(setup_done: TestClient) -> None:
    add_memory(setup_done, "ユーザーはラーメンが好き")
    add_memory(setup_done, "ユーザーは几帳面", "habit")
    assert [m["content"] for m in setup_done.get("/api/memories?q=らーめん").json()] == []
    assert [m["content"] for m in setup_done.get("/api/memories?q=ラーメン").json()] == ["ユーザーはラーメンが好き"]
    assert [m["content"] for m in setup_done.get("/api/memories?category=habit").json()] == ["ユーザーは几帳面"]


def test_update_memory_reindexes(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    m = add_memory(setup_done, "ユーザーは犬が好き")
    updated = setup_done.put(f"/api/memories/{m['id']}", json={"content": "ユーザーは猫が好き"}).json()
    assert updated["content"] == "ユーザーは猫が好き"
    assert updated["confirmation_status"] == "confirmed"
    events = chat(setup_done, "猫")
    assert any(e["type"] == "memories_used" for e in events)


def test_manual_important_memory_is_marked(setup_done: TestClient) -> None:
    m = add_memory(setup_done, "ユーザーは東京在住", "personal")
    assert (m["status"], m["sensitivity"], m["source_type"]) == ("active", "important", "user_manual")


def test_delete_removes_from_sqlite_and_chroma(setup_done: TestClient) -> None:
    m = add_memory(setup_done, "ユーザーはラーメンが好き")
    assert index_ids(setup_done) == {m["id"]}
    assert setup_done.delete(f"/api/memories/{m['id']}").status_code == 200
    assert setup_done.get("/api/memories").json() == []
    assert index_ids(setup_done) == set()
    assert setup_done.delete(f"/api/memories/{m['id']}").status_code == 404


def test_delete_rolls_back_when_index_fails(setup_done: TestClient, monkeypatch) -> None:  # noqa: ANN001
    m = add_memory(setup_done, "ユーザーはラーメンが好き")
    index = setup_done.app.state.services.index

    def fail(ids: list[str]) -> None:
        raise RuntimeError("chroma down")

    monkeypatch.setattr(index, "delete", fail)
    raw = TestClient(setup_done.app, raise_server_exceptions=False, headers={"Origin": "http://127.0.0.1:8765"})
    assert raw.delete(f"/api/memories/{m['id']}").status_code == 500
    assert len(setup_done.get("/api/memories").json()) == 1


def test_reject_deletes_pending(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction = [{"content": "ユーザーは山田という名字", "category": "personal", "importance": 7, "sensitive": True}]
    chat(setup_done, "山田です", create_conversation(setup_done))
    pending_id = setup_done.get("/api/memories?status=pending").json()[0]["id"]
    assert setup_done.post(f"/api/memories/{pending_id}/reject").status_code == 200
    assert setup_done.get("/api/memories").json() == []
    assert "山田という名字".encode() not in raw_db(setup_done)


def test_approve_with_edit_and_state_errors(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction = [{"content": "ユーザーは東京在住", "category": "personal", "importance": 6, "sensitive": True}]
    chat(setup_done, "東京に住んでる", create_conversation(setup_done))
    pid = setup_done.get("/api/memories?status=pending").json()[0]["id"]
    approved = setup_done.post(f"/api/memories/{pid}/approve", json={"content": "ユーザーは東京都在住"}).json()
    assert approved["content"] == "ユーザーは東京都在住"
    assert setup_done.post(f"/api/memories/{pid}/approve").status_code == 409
    assert setup_done.post(f"/api/memories/{pid}/reject").status_code == 409


def test_source_title_is_shown(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    fake_ollama.extraction = [{"content": "ユーザーは猫を飼っている", "category": "fact", "importance": 5, "sensitive": False}]
    cid = create_conversation(setup_done)
    chat(setup_done, "うちの猫がかわいい", cid)
    m = setup_done.get("/api/memories").json()[0]
    assert m["source_conversation_title"] == "うちの猫がかわいい"


@pytest.mark.parametrize("delete_memories", [True, False])
def test_delete_conversation(setup_done: TestClient, fake_ollama: FakeOllama, delete_memories: bool) -> None:
    fake_ollama.extraction = [{"content": "ユーザーは猫を飼っている", "category": "fact", "importance": 5, "sensitive": False}]
    cid = create_conversation(setup_done)
    chat(setup_done, "うちの猫", cid)
    url = f"/api/conversations/{cid}?delete_memories={'true' if delete_memories else 'false'}"
    assert setup_done.delete(url).status_code == 200
    assert setup_done.get("/api/conversations").json() == []
    memories = setup_done.get("/api/memories").json()
    if delete_memories:
        assert memories == [] and index_ids(setup_done) == set()
    else:
        assert memories[0]["source_conversation_id"] is None
        assert memories[0]["source_conversation_title"] is None


def test_reconcile_removes_orphans(setup_done: TestClient) -> None:
    services = setup_done.app.state.services
    services.index.upsert(EMBED, ["f" * 32], [[1.0] + [0.0] * 10])
    m = add_memory(setup_done, "ユーザーはラーメンが好き")
    result = setup_done.post("/api/memories/reindex").json()
    assert result["removed_orphans"] == 1
    assert index_ids(setup_done) == {m["id"]}


def test_memory_id_is_validated(setup_done: TestClient) -> None:
    assert setup_done.delete("/api/memories/..%2F..%2Fx").status_code in (404, 405, 422)
    assert setup_done.put("/api/memories/abc", json={"content": "x"}).status_code == 422


def test_stats(setup_done: TestClient) -> None:
    add_memory(setup_done, "ユーザーはラーメンが好き")
    stats = setup_done.get("/api/memories/stats").json()
    assert stats == {"active": 1, "pending": 0, "unindexed": 0, "embedding_model": EMBED, "embedding_available": True}
