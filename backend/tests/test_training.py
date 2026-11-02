from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.crypto import PREFIX
from app.training import runner
from app.training.data import quality_warnings
from tests.conftest import FakeOllama, sse_events

FAKE_TRAINER = r'''
import json, sys, pathlib, time
time.sleep(1.5)  # 学習中の状態をテストで確認できるようにする
run = pathlib.Path(sys.argv[sys.argv.index("--run-dir") + 1])
data = (run / "train.jsonl").read_text(encoding="utf-8").splitlines()
(run / "adapter").mkdir()
(run / "metrics.json").write_text(json.dumps({"eval_loss_before": 2.0, "eval_loss_after": 1.2, "train_examples": len(data),
    "samples": [{"prompt": "自己紹介をしてください。", "before": "前", "after": "後"}]}), encoding="utf-8")
(run / "status.json").write_text(json.dumps({"state": MODE, "phase": "完了", "error": "GPUメモリが不足しました。"}), encoding="utf-8")
print("loss=1.2")
'''


def save_conversation(client: TestClient, pairs: int = 6) -> str:
    cid = client.post("/api/conversations", json={"messages": []}).json()["id"]
    for i in range(pairs):
        client.post("/api/chat", json={"messages": [{"role": "user", "content": f"質問{i}について教えて"}], "conversation_id": cid})
    return cid


def approve_all(client: TestClient) -> None:
    for ex in client.get("/api/training/examples", params={"status": "pending"}).json()["examples"]:
        client.post(f"/api/training/examples/{ex['id']}/approve")


# ---------- 学習データ ----------


def test_examples_only_from_saved_conversations(setup_done: TestClient) -> None:
    # 保存しない会話は会話IDが無いので、学習データにする手段がない
    sse_events(setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "保存しない"}]}).text)
    assert setup_done.get("/api/training/examples").json()["examples"] == []
    cid = save_conversation(setup_done, 3)
    assert setup_done.post("/api/training/examples/from-conversation", json={"conversation_id": cid}).json() == {"created": 3}
    data = setup_done.get("/api/training/examples").json()
    assert data["counts"] == {"pending": 3, "approved": 0, "rejected": 0}
    assert {e["source"] for e in data["examples"]} == {"conversation"}
    # 同じ会話を再度取り込んでも重複しない
    assert setup_done.post("/api/training/examples/from-conversation", json={"conversation_id": cid}).json() == {"created": 0}


def test_examples_are_encrypted_and_editable(setup_done: TestClient) -> None:
    ex = setup_done.post("/api/training/examples", json={"user_text": "朝ごはんは？", "assistant_text": "パンかな"}).json()
    assert ex["status"] == "pending"
    edited = setup_done.put(f"/api/training/examples/{ex['id']}", json={"assistant_text": "ご飯と味噌汁が理想だね"}).json()
    assert edited["assistant_text"] == "ご飯と味噌汁が理想だね"
    with setup_done.app.state.services.db.transaction() as conn:
        row = conn.execute("SELECT user_text, assistant_text, fingerprint FROM training_examples").fetchone()
    assert row[0].startswith(PREFIX) and row[1].startswith(PREFIX)
    assert "朝ごはん" not in row[2]


def test_replace_from_keeps_template() -> None:
    modelfile = '# comment\n# FROM old\nFROM C:\\blobs\\sha\nTEMPLATE """\n# not a comment\nFROM inside template\n"""\nPARAMETER stop "<|im_end|>"\n'
    out = runner.replace_from(modelfile, "./model-f16.gguf")
    assert out.startswith("FROM ./model-f16.gguf\n")
    assert "# not a comment" in out and "FROM inside template" in out and "PARAMETER stop" in out
    assert "C:\\blobs" not in out


def test_quality_warnings() -> None:
    assert any("短すぎ" in w for w in quality_warnings("あ", "い"))
    assert any("電話番号" in w for w in quality_warnings("連絡先は090-1234-5678", "了解"))
    assert any("メール" in w for w in quality_warnings("taro@example.com に送って", "了解"))
    assert quality_warnings("今日の夕飯どうしよう", "カレーはどう？") == []


def test_duplicate_manual_example_rejected(setup_done: TestClient) -> None:
    body = {"user_text": "こんにちは", "assistant_text": "やあ、元気？"}
    assert setup_done.post("/api/training/examples", json=body).status_code == 200
    assert setup_done.post("/api/training/examples", json={"user_text": "こんにちは。", "assistant_text": "やあ 元気?"}).status_code == 409


def test_dedupe_after_edit(setup_done: TestClient) -> None:
    a = setup_done.post("/api/training/examples", json={"user_text": "A質問", "assistant_text": "A回答"}).json()
    b = setup_done.post("/api/training/examples", json={"user_text": "B質問", "assistant_text": "B回答"}).json()
    setup_done.post(f"/api/training/examples/{a['id']}/approve")
    setup_done.put(f"/api/training/examples/{b['id']}", json={"user_text": "A質問", "assistant_text": "A回答"})
    assert setup_done.post("/api/training/examples/dedupe").json() == {"removed": 1}
    remaining = setup_done.get("/api/training/examples").json()["examples"]
    assert [e["id"] for e in remaining] == [a["id"]]  # 承認済みが残る


def test_export_requires_confirmation_and_only_approved(setup_done: TestClient) -> None:
    a = setup_done.post("/api/training/examples", json={"user_text": "承認する質問", "assistant_text": "回答1"}).json()
    setup_done.post("/api/training/examples", json={"user_text": "未承認の質問", "assistant_text": "回答2"})
    setup_done.post(f"/api/training/examples/{a['id']}/approve")
    assert setup_done.post("/api/training/examples/export", json={"confirmed": False}).status_code == 400
    r = setup_done.post("/api/training/examples/export", json={"confirmed": True})
    lines = [json.loads(line) for line in r.text.splitlines()]
    assert len(lines) == 1
    assert [m["role"] for m in lines[0]["messages"]] == ["system", "user", "assistant"]
    assert lines[0]["messages"][1]["content"] == "承認する質問"


def test_distill_creates_pending_examples(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    a = setup_done.post("/api/training/examples", json={"user_text": "休日の過ごし方は？", "assistant_text": "寝る"}).json()
    setup_done.post(f"/api/training/examples/{a['id']}/approve")
    fake_ollama.extraction_raw = None
    r = setup_done.post("/api/training/distill", json={"limit": 3}).json()
    assert r["teacher"] == "qwen3:8b"
    pending = setup_done.get("/api/training/examples", params={"status": "pending"}).json()["examples"]
    assert [(p["source"], p["user_text"]) for p in pending] == [("distill", "休日の過ごし方は？")]


# ---------- 学習の実行 ----------


@pytest.fixture
def fake_env(tmp_path: Path, config, monkeypatch):  # noqa: ANN001, ANN201
    """GPU を使わない偽の学習スクリプトと、ダウンロード済み扱いのベースモデルを用意する。"""
    base = config.models_dir / "hf" / "Qwen3-1.7B"
    base.mkdir(parents=True)
    (base / "config.json").write_text("{}")
    script = tmp_path / "fake_train.py"

    def use(mode: str) -> None:
        script.write_text(f"MODE = {mode!r}\n" + FAKE_TRAINER, encoding="utf-8")

    use("succeeded")
    monkeypatch.setattr(runner, "TRAINING_PYTHON", Path(sys.executable))
    monkeypatch.setattr(runner, "TRAIN_SCRIPT", script)
    monkeypatch.setattr(runner.TrainingManager, "_register_with_ollama", lambda self, run_id, run_dir: f"twin-qwen3-1.7b-{run_id[:8]}")
    return use


def wait_done(client: TestClient, run_id: str) -> dict:
    for _ in range(60):
        run = next(r for r in client.get("/api/training/runs").json()["runs"] if r["id"] == run_id)
        if run["status"] != "running":
            return run
        time.sleep(0.25)
    raise AssertionError("training did not finish")


PARAMS = {"base": "qwen3-1.7b", "epochs": 1, "confirmed": True}


def test_start_requires_confirmation_and_enough_data(setup_done: TestClient, fake_env) -> None:  # noqa: ANN001
    r = setup_done.post("/api/training/runs", json={**PARAMS, "confirmed": False})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "confirmation_required"
    r = setup_done.post("/api/training/runs", json=PARAMS)
    assert r.json()["detail"]["code"] == "not_enough_data"
    assert "5件以上" in r.json()["detail"]["message"]


def test_start_requires_downloaded_base(setup_done: TestClient) -> None:
    r = setup_done.post("/api/training/runs", json={**PARAMS, "base": "qwen3-8b"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "base_missing"


def test_training_lifecycle(setup_done: TestClient, fake_env, fake_ollama: FakeOllama, config) -> None:  # noqa: ANN001
    cid = save_conversation(setup_done, 6)
    setup_done.post("/api/training/examples/from-conversation", json={"conversation_id": cid})
    approve_all(setup_done)
    run = setup_done.post("/api/training/runs", json=PARAMS).json()
    assert run["status"] == "running" and run["example_count"] == 6
    # 学習前に Ollama のモデルを解放してから開始する
    assert any(r["path"] == "/api/ps" for r in fake_ollama.requests)

    # 学習中は会話できない（GPU メモリの取り合いで学習が失敗するため）
    r = setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "こんにちは"}]})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "training_running"

    done = wait_done(setup_done, run["id"])
    assert done["status"] == "succeeded"
    assert setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "こんにちは"}]}).status_code == 200
    assert done["metrics"]["eval_loss_after"] < done["metrics"]["eval_loss_before"]
    assert done["ollama_model"].startswith("twin-qwen3-1.7b-")

    run_dir = config.data_dir / "training" / "runs" / run["id"]
    # 平文の学習データ・プロフィール・回答例は残さない。学習データは暗号化して保存される
    assert not (run_dir / "train.jsonl").exists()
    assert not (run_dir / "metrics.json").exists()
    assert "system_prompt" not in json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    assert (run_dir / "dataset.enc").read_text().startswith(PREFIX)
    assert "loss=1.2" in setup_done.get(f"/api/training/runs/{run['id']}/log").json()["log"]

    # 切り替えと元に戻す
    setup_done.post(f"/api/training/runs/{run['id']}/activate")
    assert setup_done.get("/api/settings").json()["model"] == done["ollama_model"]
    assert setup_done.post("/api/training/revert").json() == {"model": "qwen3:8b"}
    assert setup_done.get("/api/settings").json()["model"] == "qwen3:8b"

    # 削除すると Ollama のモデルとファイルも消える
    setup_done.post(f"/api/training/runs/{run['id']}/activate")
    assert setup_done.delete(f"/api/training/runs/{run['id']}").status_code == 200
    assert setup_done.get("/api/settings").json()["model"] == "qwen3:8b"
    assert not run_dir.exists()


def test_failed_training_is_reported(setup_done: TestClient, fake_env) -> None:  # noqa: ANN001
    fake_env("failed")
    for i in range(5):
        ex = setup_done.post("/api/training/examples", json={"user_text": f"質問{i}", "assistant_text": f"回答{i}"}).json()
        setup_done.post(f"/api/training/examples/{ex['id']}/approve")
    run = setup_done.post("/api/training/runs", json=PARAMS).json()
    done = wait_done(setup_done, run["id"])
    assert done["status"] == "failed" and "GPUメモリ" in done["error"]
    assert setup_done.post(f"/api/training/runs/{run['id']}/activate").status_code == 409


def test_interrupted_run_is_recovered(setup_done: TestClient, make_client, config) -> None:  # noqa: ANN001
    services = setup_done.app.state.services
    run_dir = config.data_dir / "training" / "runs" / ("a" * 32)
    run_dir.mkdir(parents=True)
    (run_dir / "train.jsonl").write_text("secret", encoding="utf-8")
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO training_runs (id, base, status, example_count, params, created_at) VALUES (?, 'qwen3-1.7b', 'running', 5, '{}', 't')",
            ("a" * 32,),
        )
    restarted = make_client()
    run = restarted.get("/api/training/runs").json()["runs"][0]
    assert run["status"] == "failed" and "中断" in run["error"]
    assert not (run_dir / "train.jsonl").exists()
