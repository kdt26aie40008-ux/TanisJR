"""VRM アバターファイルの検証・保存。

ファイルは data/avatars/<id>.vrm にサーバー側で決めた名前で保存する（利用者が指定したファイル名をパスに使わない）。
リポジトリーに同梱した標準アバター（assets/avatars）は全ユーザーが選べる。DB には登録せず、変更・削除はできない。
"""

from __future__ import annotations

import json
import os
import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.config import REPO_ROOT
from app.db import Database, now_iso

BUILTIN_DIR = REPO_ROOT / "assets" / "avatars"


@dataclass(frozen=True)
class BuiltinAvatar:
    id: str
    file: str
    name: str


# id は固定（選択状態を設定に保存するため変更しない）
BUILTIN_AVATARS: tuple[BuiltinAvatar, ...] = (
    BuiltinAvatar("b0000000000000000000000000000001", "tanisjr-male.vrm", "標準アバター（男性）"),
    BuiltinAvatar("b0000000000000000000000000000002", "tanisjr-female.vrm", "標準アバター（女性）"),
)

MAX_AVATAR_BYTES = 100 * 1024 * 1024
_GLB_HEADER = struct.Struct("<4sII")
_CHUNK_HEADER = struct.Struct("<I4s")
_MAX_TEXT = 300


class AvatarError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class Avatar(BaseModel):
    id: str
    name: str
    size: int
    is_placeholder: bool
    vrm_version: str
    meta: dict[str, Any]
    created_at: str
    builtin: bool = False


def _text(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value or "")[:_MAX_TEXT]


def parse_vrm(data: bytes) -> tuple[str, dict[str, Any]]:
    """GLB を検証し、(VRMバージョン, ライセンス等のメタ情報) を返す。"""
    if len(data) < _GLB_HEADER.size + _CHUNK_HEADER.size:
        raise AvatarError("VRMファイル（.vrm）ではありません。")
    magic, version, length = _GLB_HEADER.unpack_from(data, 0)
    if magic != b"glTF" or version != 2:
        raise AvatarError("VRMファイル（.vrm）ではありません。")
    if length != len(data):
        raise AvatarError("ファイルが壊れているか、途中までしか読み込まれていません。")
    chunk_len, chunk_type = _CHUNK_HEADER.unpack_from(data, _GLB_HEADER.size)
    start = _GLB_HEADER.size + _CHUNK_HEADER.size
    if chunk_type != b"JSON" or start + chunk_len > len(data):
        raise AvatarError("ファイルが壊れています。")
    try:
        gltf = json.loads(data[start:start + chunk_len])
    except ValueError as exc:
        raise AvatarError("ファイルが壊れています。") from exc
    extensions = gltf.get("extensions") or {}

    if "VRMC_vrm" in extensions:
        meta = (extensions["VRMC_vrm"] or {}).get("meta") or {}
        return "1.0", {
            "name": _text(meta.get("name")),
            "authors": _text(meta.get("authors")),
            "copyright": _text(meta.get("copyrightInformation")),
            "license_url": _text(meta.get("licenseUrl")),
            "avatar_permission": _text(meta.get("avatarPermission")),
            "commercial_usage": _text(meta.get("commercialUsage")),
            "credit_required": meta.get("creditNotation") == "required",
            "allow_redistribution": bool(meta.get("allowRedistribution")),
            "modification": _text(meta.get("modification")),
        }
    if "VRM" in extensions:
        meta = (extensions["VRM"] or {}).get("meta") or {}
        return "0.x", {
            "name": _text(meta.get("title")),
            "authors": _text(meta.get("author")),
            "copyright": "",
            "license_url": _text(meta.get("otherPermissionUrl") or meta.get("otherLicenseUrl")),
            "avatar_permission": _text(meta.get("allowedUserName")),
            "commercial_usage": _text(meta.get("commercialUssageName")),
            "license_name": _text(meta.get("licenseName")),
            # VRM 0.x にはクレジット表記の項目が無いため、作者名は常に表示する
            "credit_required": True,
            # "Other" は条件が個別なので再配布不可として扱う
            "allow_redistribution": meta.get("licenseName") not in {None, "", "Redistribution_Prohibited", "Other"},
            "modification": "",
        }
    raise AvatarError("VRMの情報が含まれていません（通常の glTF/GLB ファイルです）。")


@dataclass
class AvatarStore:
    db: Database
    directory: Path
    builtin_dir: Path | None = None  # None なら BUILTIN_DIR
    _builtin_cache: dict[str, Avatar] = field(default_factory=dict, init=False, repr=False)

    def _builtin_path(self, b: BuiltinAvatar) -> Path:
        return (self.builtin_dir or BUILTIN_DIR) / b.file

    def path_for(self, avatar_id: str) -> Path:
        for b in BUILTIN_AVATARS:
            if b.id == avatar_id:
                return self._builtin_path(b)
        return self.directory / f"{uuid.UUID(hex=avatar_id).hex}.vrm"

    def is_builtin(self, avatar_id: str) -> bool:
        return any(b.id == avatar_id for b in BUILTIN_AVATARS)

    def builtins(self) -> list[Avatar]:
        """同梱ファイルがあるものだけを返す（ファイルが無い・壊れている場合は表示しない）。"""
        result = []
        for b in BUILTIN_AVATARS:
            if b.id not in self._builtin_cache:
                path = self._builtin_path(b)
                try:
                    vrm_version, meta = parse_vrm(path.read_bytes())
                except (OSError, AvatarError):
                    continue
                self._builtin_cache[b.id] = Avatar(
                    id=b.id, name=b.name, size=path.stat().st_size, is_placeholder=False,
                    vrm_version=vrm_version, meta=meta, created_at="", builtin=True,
                )
            result.append(self._builtin_cache[b.id])
        return result

    def add(self, data: bytes, name: str, is_placeholder: bool) -> Avatar:
        if len(data) > MAX_AVATAR_BYTES:
            raise AvatarError("ファイルが大きすぎます（100MBまで）。", 413)
        vrm_version, meta = parse_vrm(data)
        avatar_id = uuid.uuid4().hex
        display = (name.strip() or meta.get("name") or "名前のないアバター")[:64]
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(avatar_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    "INSERT INTO avatars (id, name, size, is_placeholder, vrm_version, meta, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (avatar_id, display, len(data), int(is_placeholder), vrm_version, json.dumps(meta, ensure_ascii=False), now_iso()),
                )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        avatar = self.get(avatar_id)
        assert avatar is not None
        return avatar

    def list(self) -> list[Avatar]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT * FROM avatars ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._to_model(r) for r in rows] + self.builtins()

    def get(self, avatar_id: str) -> Avatar | None:
        if self.is_builtin(avatar_id):
            return next((a for a in self.builtins() if a.id == avatar_id), None)
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM avatars WHERE id = ?", (avatar_id,)).fetchone()
        return self._to_model(row) if row else None

    def update(self, avatar_id: str, name: str | None, is_placeholder: bool | None) -> Avatar | None:
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name.strip()[:64] or "名前のないアバター"
        if is_placeholder is not None:
            fields["is_placeholder"] = int(is_placeholder)
        if fields:
            with self.db.transaction() as conn:
                sets = ", ".join(f"{k} = ?" for k in fields)
                conn.execute(f"UPDATE avatars SET {sets} WHERE id = ?", (*fields.values(), avatar_id))
        return self.get(avatar_id)

    def delete(self, avatar_id: str) -> bool:
        with self.db.transaction() as conn:
            deleted = conn.execute("DELETE FROM avatars WHERE id = ?", (avatar_id,)).rowcount > 0
        if deleted:
            self.path_for(avatar_id).unlink(missing_ok=True)
        return deleted

    @staticmethod
    def _to_model(row: Any) -> Avatar:
        data = dict(row)
        data["meta"] = json.loads(data["meta"])
        data["is_placeholder"] = bool(data["is_placeholder"])
        return Avatar(**data)
