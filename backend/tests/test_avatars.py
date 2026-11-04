from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.avatars import BUILTIN_AVATARS, parse_vrm
from app.config import REPO_ROOT

MALE_ID = BUILTIN_AVATARS[0].id


@pytest.fixture(autouse=True)
def builtin_dir(tmp_path: Path, monkeypatch) -> Path:  # noqa: ANN001
    """同梱の標準アバターを、テストごとの空フォルダーに差し替える。"""
    directory = tmp_path / "builtin"
    directory.mkdir()
    monkeypatch.setattr("app.avatars.BUILTIN_DIR", directory)
    return directory

VRM1_META = {
    "name": "テストちゃん",
    "authors": ["作者A"],
    "licenseUrl": "https://vrm.dev/licenses/1.0/",
    "avatarPermission": "onlyAuthor",
    "commercialUsage": "personalNonProfit",
    "creditNotation": "required",
    "allowRedistribution": False,
    "modification": "prohibited",
}


def make_glb(gltf: dict, declared_length: int | None = None) -> bytes:
    body = json.dumps(gltf).encode()
    body += b" " * (-len(body) % 4)
    chunk = struct.pack("<I4s", len(body), b"JSON") + body
    total = 12 + len(chunk)
    return struct.pack("<4sII", b"glTF", 2, declared_length or total) + chunk


def vrm1() -> bytes:
    return make_glb({"asset": {"version": "2.0"}, "extensions": {"VRMC_vrm": {"specVersion": "1.0", "meta": VRM1_META}}})


def vrm0() -> bytes:
    meta = {"title": "旧モデル", "author": "作者B", "licenseName": "CC_BY", "allowedUserName": "Everyone"}
    return make_glb({"asset": {"version": "2.0"}, "extensions": {"VRM": {"meta": meta}}})


def upload(client: TestClient, data: bytes, **params: object):  # noqa: ANN201
    return client.post("/api/avatars", params=params, content=data, headers={"Content-Type": "application/octet-stream"})


def test_upload_vrm1_extracts_license(client: TestClient, config) -> None:  # noqa: ANN001
    response = upload(client, vrm1(), placeholder=True)
    assert response.status_code == 200, response.text
    avatar = response.json()
    assert avatar["name"] == "テストちゃん"
    assert avatar["vrm_version"] == "1.0"
    assert avatar["is_placeholder"] is True
    assert avatar["meta"]["credit_required"] is True
    assert avatar["meta"]["authors"] == "作者A"
    assert avatar["meta"]["allow_redistribution"] is False
    # 保存ファイル名はサーバーが決める
    assert (config.data_dir / "avatars" / f"{avatar['id']}.vrm").read_bytes() == vrm1()
    # 最初のアバターは自動で選択される
    assert client.get("/api/avatars").json()["active_id"] == avatar["id"]


def test_upload_vrm0(client: TestClient) -> None:
    avatar = upload(client, vrm0(), name="表示名").json()
    assert avatar["name"] == "表示名"
    assert avatar["vrm_version"] == "0.x"
    assert avatar["meta"]["license_name"] == "CC_BY"
    assert avatar["meta"]["allow_redistribution"] is True


def test_rejects_non_vrm(client: TestClient) -> None:
    cases = {
        b"PK\x03\x04 zip file pretending": "VRMファイル",
        make_glb({"asset": {"version": "2.0"}}): "VRMの情報",
        make_glb({"asset": {}}, declared_length=99999): "壊れて",
        struct.pack("<4sII", b"glTF", 2, 20) + struct.pack("<I4s", 100, b"JSON"): "壊れて",
    }
    for data, message in cases.items():
        response = upload(client, data)
        assert response.status_code == 400, data[:10]
        assert message in response.json()["detail"]["message"]
    assert client.get("/api/avatars").json()["avatars"] == []


def test_rejects_too_large(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("app.routers.avatars.MAX_AVATAR_BYTES", 10)
    assert upload(client, vrm1()).status_code == 413


def test_serve_file(client: TestClient) -> None:
    avatar = upload(client, vrm1()).json()
    response = client.get(f"/api/avatars/{avatar['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.content == vrm1()


def test_id_validation(client: TestClient) -> None:
    assert client.get("/api/avatars/..%2F..%2Ftwin.db/file").status_code in (404, 422)
    assert client.get("/api/avatars/notanid/file").status_code == 422
    assert client.get(f"/api/avatars/{'0' * 32}/file").status_code == 404


def test_activate_rename_and_delete(client: TestClient, config) -> None:  # noqa: ANN001
    a = upload(client, vrm1()).json()
    b = upload(client, vrm0()).json()
    assert client.get("/api/avatars").json()["active_id"] == a["id"]
    assert client.post(f"/api/avatars/{b['id']}/activate").status_code == 200
    assert client.get("/api/settings").json()["avatar_id"] == b["id"]
    renamed = client.put(f"/api/avatars/{b['id']}", json={"name": "新しい名前", "is_placeholder": False}).json()
    assert renamed["name"] == "新しい名前"
    assert client.delete(f"/api/avatars/{b['id']}").status_code == 200
    assert not (config.data_dir / "avatars" / f"{b['id']}.vrm").exists()
    # 選択中を削除したら未選択になる
    assert client.get("/api/avatars").json()["active_id"] is None
    assert client.delete(f"/api/avatars/{b['id']}").status_code == 404


def test_builtin_avatars_listed_and_selectable(client: TestClient, builtin_dir: Path) -> None:
    (builtin_dir / BUILTIN_AVATARS[0].file).write_bytes(vrm1())
    # 女性用のファイルが無い場合は一覧に出さない
    avatars = client.get("/api/avatars").json()["avatars"]
    assert [(a["id"], a["builtin"]) for a in avatars] == [(MALE_ID, True)]
    assert avatars[0]["name"] == BUILTIN_AVATARS[0].name
    # アップロードしたものは標準アバターより前に並ぶ
    mine = upload(client, vrm0()).json()
    assert [a["id"] for a in client.get("/api/avatars").json()["avatars"]] == [mine["id"], MALE_ID]

    assert client.post(f"/api/avatars/{MALE_ID}/activate").status_code == 200
    assert client.get("/api/avatars").json()["active_id"] == MALE_ID
    assert client.get(f"/api/avatars/{MALE_ID}/file").content == vrm1()
    # 変更・削除はできない
    assert client.put(f"/api/avatars/{MALE_ID}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/api/avatars/{MALE_ID}").status_code == 403
    assert (builtin_dir / BUILTIN_AVATARS[0].file).exists()


def test_bundled_avatar_files_allow_redistribution() -> None:
    """リポジトリーに同梱する VRM は、全員が利用・再配布できる設定になっていること。"""
    for b in BUILTIN_AVATARS:
        version, meta = parse_vrm((REPO_ROOT / "assets" / "avatars" / b.file).read_bytes())
        assert version == "1.0"
        assert meta["avatar_permission"] == "everyone"
        assert meta["allow_redistribution"] is True


def test_avatar_settings_cannot_be_set_directly(client: TestClient) -> None:
    assert client.put("/api/settings", json={"avatar_id": "x"}).status_code == 422
    assert client.put("/api/settings", json={"tts_acknowledged_speakers": ["x"]}).status_code == 422
