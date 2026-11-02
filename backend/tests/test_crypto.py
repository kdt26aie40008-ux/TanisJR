from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.crypto import PREFIX, CryptoError, DataLocked, DpapiProtector, FieldCipher, KeyStore, Vault
from app.db import Database
from tests.conftest import VALID_SETUP


def test_field_cipher_roundtrip_and_randomized() -> None:
    cipher = FieldCipher(os.urandom(32))
    a, b = cipher.encrypt("秘密のメモ"), cipher.encrypt("秘密のメモ")
    assert a.startswith(PREFIX) and a != b
    assert cipher.decrypt(a) == "秘密のメモ"


def test_field_cipher_rejects_wrong_key_and_tampering() -> None:
    token = FieldCipher(os.urandom(32)).encrypt("x")
    with pytest.raises(CryptoError):
        FieldCipher(os.urandom(32)).decrypt(token)
    cipher = FieldCipher(os.urandom(32))
    token = cipher.encrypt("hello")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(CryptoError):
        cipher.decrypt(tampered)


def test_legacy_plaintext_passes_through() -> None:
    assert FieldCipher(os.urandom(32)).decrypt("平文") == "平文"


def test_dpapi_roundtrip(tmp_path: Path) -> None:
    protector = DpapiProtector()
    protected = protector.protect(b"k" * 32)
    assert b"k" * 32 not in protected
    assert protector.unprotect(protected) == b"k" * 32
    store = KeyStore(tmp_path / "keys" / "master.key", protector)
    key = store.create()
    assert store.load() == key
    assert key not in (tmp_path / "keys" / "master.key").read_bytes()


def test_vault_locked_raises() -> None:
    vault = Vault()
    vault.lock("鍵がありません")
    with pytest.raises(DataLocked, match="鍵がありません"):
        vault.encrypt("x")


def test_profile_is_encrypted_at_rest(setup_done: TestClient) -> None:
    db: Database = setup_done.app.state.services.db
    with db.transaction() as conn:
        contents = [r[0] for r in conn.execute("SELECT content FROM profile_entries")]
    assert all(c.startswith(PREFIX) for c in contents)
    raw = b"".join(p.read_bytes() for p in db.path.parent.glob("twin.db*"))
    assert "山田太郎".encode() not in raw
    # API からは復号された内容が見える
    assert setup_done.get("/api/profile").json()[0]["content"] == VALID_SETUP["answers"][0]


def test_locked_when_key_missing(setup_done: TestClient, make_client: Callable[[], TestClient], config) -> None:  # noqa: ANN001
    (config.data_dir / "keys" / "master.key").unlink()
    locked = make_client()
    health = locked.get("/api/health").json()
    assert health["data_locked"] is True
    assert "バックアップ" in health["locked_reason"]
    response = locked.get("/api/profile")
    assert response.status_code == 423
    assert response.json()["detail"]["code"] == "data_locked"
    chat = locked.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert chat.status_code == 423
    # データ自体は消えていない
    with locked.app.state.services.db.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM profile_entries").fetchone()[0] == 3


def test_locked_when_key_mismatch(setup_done: TestClient, make_client: Callable[[], TestClient], config) -> None:  # noqa: ANN001
    from tests.conftest import FakeProtector

    KeyStore(config.data_dir / "keys" / "master.key", FakeProtector()).create()
    locked = make_client()
    assert locked.get("/api/health").json()["data_locked"] is True


def test_legacy_plaintext_profile_is_encrypted_on_startup(config, make_client: Callable[[], TestClient]) -> None:  # noqa: ANN001
    # Phase 1 の状態（鍵なし・平文のプロフィール）を再現する
    db = Database(config.db_path)
    db.migrate()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO profile_entries (key, question, content, source, importance, confirmation_status, created_at, updated_at) "
            "VALUES ('setup.q1_identity', 'q', '旧データ平文', 'initial_setup', 10, 'confirmed', 't', 't')"
        )
    c = make_client()
    assert c.get("/api/health").json()["data_locked"] is False
    with db.transaction() as conn:
        assert conn.execute("SELECT content FROM profile_entries").fetchone()[0].startswith(PREFIX)
    assert c.get("/api/profile").json()[0]["content"] == "旧データ平文"
