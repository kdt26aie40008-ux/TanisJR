from __future__ import annotations

import base64
import os
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.backup import BackupError, create_backup, read_backup
from tests.conftest import FakeOllama

PASS = "correct horse battery"


def make_backup(client: TestClient, passphrase: str = PASS) -> bytes:
    response = client.post("/api/backup", json={"passphrase": passphrase})
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    return response.content


def restore(client: TestClient, blob: bytes, passphrase: str = PASS):  # noqa: ANN201
    return client.post("/api/backup/restore", json={"passphrase": passphrase, "data": base64.b64encode(blob).decode()})


def test_backup_file_is_encrypted(setup_done: TestClient) -> None:
    blob = make_backup(setup_done)
    assert blob.startswith(b"TWINBK01")
    assert "山田太郎".encode() not in blob


def test_backup_requires_long_passphrase(setup_done: TestClient) -> None:
    response = setup_done.post("/api/backup", json={"passphrase": "short"})
    assert response.status_code == 400
    assert "10文字以上" in response.json()["detail"]["message"]


def test_wrong_passphrase_and_corruption(config) -> None:  # noqa: ANN001
    from app.db import Database

    db = Database(config.db_path)
    db.migrate()
    blob = create_backup(db.path, os.urandom(32), PASS)
    with pytest.raises(BackupError, match="パスフレーズ"):
        read_backup(blob, "wrong passphrase!!")
    with pytest.raises(BackupError):
        read_backup(blob[:-5] + b"xxxxx", PASS)
    with pytest.raises(BackupError, match="バックアップファイルではありません"):
        read_backup(b"not a backup", PASS)


def test_restore_roundtrip(setup_done: TestClient, fake_ollama: FakeOllama) -> None:
    setup_done.post("/api/memories", json={"content": "ユーザーはラーメンが好き", "category": "preference"})
    blob = make_backup(setup_done)

    # バックアップ後の変更は復元で元に戻る
    setup_done.put("/api/profile", json={"key": "setup.q1_identity", "content": "変更後"})
    mid = setup_done.get("/api/memories").json()[0]["id"]
    setup_done.delete(f"/api/memories/{mid}")

    response = restore(setup_done, blob)
    assert response.status_code == 200, response.text
    assert setup_done.get("/api/profile").json()[0]["content"] == "山田太郎。エンジニアです。"
    memories = setup_done.get("/api/memories").json()
    assert [m["content"] for m in memories] == ["ユーザーはラーメンが好き"]
    # 索引も作り直され、検索に使える
    services = setup_done.app.state.services
    assert services.index.ids("qwen3-embedding:0.6b") == {memories[0]["id"]}


def test_restore_on_new_pc_unlocks_data(setup_done: TestClient, make_client: Callable[[], TestClient], config) -> None:  # noqa: ANN001
    blob = make_backup(setup_done)
    # 別PC相当: 鍵ファイルが無くなりロック状態になる
    (config.data_dir / "keys" / "master.key").unlink()
    locked = make_client()
    assert locked.get("/api/health").json()["data_locked"] is True
    assert restore(locked, blob).status_code == 200
    assert locked.get("/api/health").json()["data_locked"] is False
    assert locked.get("/api/profile").json()[0]["content"] == "山田太郎。エンジニアです。"


def test_restore_wrong_passphrase_keeps_current_data(setup_done: TestClient) -> None:
    blob = make_backup(setup_done)
    response = restore(setup_done, blob, "wrong passphrase!!")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "backup_error"
    assert setup_done.get("/api/profile").json()[0]["content"] == "山田太郎。エンジニアです。"


def test_restore_rejects_invalid_base64(setup_done: TestClient) -> None:
    response = setup_done.post("/api/backup/restore", json={"passphrase": PASS, "data": "!!!"})
    assert response.status_code == 400
