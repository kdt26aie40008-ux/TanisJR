from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import default_data_dir, load_config
from app.crypto import KeyStore
from app.data_location import RESET_FLAG, apply_start_fresh, migrate_legacy_data
from tests.conftest import FakeProtector


class OtherUserProtector(FakeProtector):
    """別の PC・別の Windows ユーザーの鍵（このユーザーの DPAPI では読めない）を再現する。"""

    def protect(self, data: bytes) -> bytes:
        return b"X" + data


def make_legacy(directory: Path, protector) -> None:  # noqa: ANN001
    (directory / "keys").mkdir(parents=True)
    (directory / "twin.db").write_bytes(b"db")
    (directory / "avatars").mkdir()
    (directory / "avatars" / "a.vrm").write_bytes(b"vrm")
    KeyStore(directory / "keys" / "master.key", protector).create()


def test_default_location_is_per_windows_user(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.delenv("TWIN_DATA_DIR", raising=False)
    assert default_data_dir() == tmp_path / "Local" / "PersonalTwinAI" / "data"
    assert load_config().data_dir == (tmp_path / "Local" / "PersonalTwinAI" / "data").resolve()
    # 環境変数で場所を指定することもできる
    monkeypatch.setenv("TWIN_DATA_DIR", str(tmp_path / "custom"))
    assert load_config().data_dir == (tmp_path / "custom").resolve()


def test_moves_this_users_old_data(tmp_path: Path) -> None:
    legacy, target = tmp_path / "repo" / "data", tmp_path / "local" / "data"
    make_legacy(legacy, FakeProtector())
    # 起動時に作られたログフォルダーがあっても統合できる
    (target / "logs").mkdir(parents=True)
    assert migrate_legacy_data(legacy, target, FakeProtector()) == "moved"
    assert (target / "twin.db").read_bytes() == b"db"
    assert (target / "avatars" / "a.vrm").exists()
    assert not legacy.exists()


def test_ignores_other_users_data(tmp_path: Path) -> None:
    """別の PC で使っていたプロジェクトフォルダーをコピーしても、そのデータは使わず空の状態から始まる。"""
    legacy, target = tmp_path / "repo" / "data", tmp_path / "local" / "data"
    make_legacy(legacy, OtherUserProtector())
    assert migrate_legacy_data(legacy, target, FakeProtector()) == "other-user-data"
    assert not (target / "twin.db").exists()
    assert (legacy / "twin.db").exists()  # 他人のデータは消さない


def test_does_not_overwrite_existing_data(tmp_path: Path) -> None:
    legacy, target = tmp_path / "repo" / "data", tmp_path / "local" / "data"
    make_legacy(legacy, FakeProtector())
    target.mkdir(parents=True)
    (target / "twin.db").write_bytes(b"current")
    assert migrate_legacy_data(legacy, target, FakeProtector()) == "target-has-data"
    assert (target / "twin.db").read_bytes() == b"current"


def test_apply_start_fresh_archives_data(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "twin.db").write_bytes(b"old")
    assert apply_start_fresh(data) is None  # 要求がなければ何もしない
    (data / RESET_FLAG).write_text("x")
    archive = apply_start_fresh(data)
    assert archive is not None and archive.name.startswith("data-archived-")
    assert (archive / "twin.db").read_bytes() == b"old"  # 削除せず退避
    assert data.exists() and list(data.iterdir()) == []


def test_start_fresh_only_when_locked(setup_done: TestClient, make_client: Callable[[], TestClient], config) -> None:  # noqa: ANN001
    r = setup_done.post("/api/system/start-fresh", json={"confirmed": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_locked"

    # 別ユーザーの鍵に置き換わった状態（ロック）を再現する
    KeyStore(config.data_dir / "keys" / "master.key", OtherUserProtector()).create()
    locked = make_client()
    assert locked.get("/api/health").json()["data_locked"] is True
    assert locked.post("/api/system/start-fresh", json={"confirmed": False}).status_code == 400
    assert locked.post("/api/system/start-fresh", json={"confirmed": True}).json() == {"restarting": False}
    # 実際の退避は次の起動時（プロセスがファイルを手放した後）に行う。退避そのものは上のテストで確認
    assert (config.data_dir / RESET_FLAG).exists()


def test_fresh_data_folder_starts_from_setup(tmp_path: Path, config, make_client) -> None:  # noqa: ANN001
    """退避後の空のフォルダーで起動すると、初回設定（3つの質問）から始まる。"""
    assert not config.data_dir.exists()
    fresh = make_client()
    assert fresh.get("/api/health").json()["data_locked"] is False
    assert fresh.get("/api/setup/status").json() == {"completed": False}
    assert fresh.get("/api/profile").json() == []
