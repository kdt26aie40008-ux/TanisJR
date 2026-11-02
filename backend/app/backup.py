"""パスフレーズで暗号化したバックアップの作成と読み込み。

形式: MAGIC(8) + salt(16) + nonce(12) + AES-256-GCM(zlib(JSON))
JSON にはマスター鍵と SQLite のスナップショットを含むため、パスフレーズがあれば
別のPC（DPAPI の鍵が無い環境）でも復元できる。
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.db import now_iso

MAGIC = b"TWINBK01"
SALT_SIZE = 16
NONCE_SIZE = 12
MIN_PASSPHRASE_LEN = 10
MAX_BACKUP_BYTES = 200 * 1024 * 1024


class BackupError(Exception):
    """ユーザーに表示できる日本語メッセージを持つ例外。"""


@dataclass(frozen=True)
class BackupContents:
    master_key: bytes
    database: bytes
    created_at: str
    schema_version: int


def _derive(passphrase: str, salt: bytes) -> bytes:
    # n=2^15, r=8 で約32MBのメモリを使い、総当たりを遅くする
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _without_wal_flag(data: bytes) -> bytes:
    """WAL モードの DB ヘッダー（オフセット18,19 = 2）のままではメモリ上で開けないため、通常モードに戻す。"""
    buf = bytearray(data)
    if len(buf) >= 20 and buf[18] == 2 and buf[19] == 2:
        buf[18] = buf[19] = 1
    return bytes(buf)


def _open_snapshot(database: bytes) -> sqlite3.Connection:
    mem = sqlite3.connect(":memory:")
    try:
        mem.deserialize(_without_wal_flag(database))
        mem.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as exc:
        mem.close()
        raise BackupError("バックアップ内のデータベースが破損しています。") from exc
    return mem


def snapshot_database(db_path: Path) -> tuple[bytes, int]:
    src = sqlite3.connect(db_path)
    mem = sqlite3.connect(":memory:")
    try:
        src.backup(mem)
        version = mem.execute("PRAGMA user_version").fetchone()[0]
        return _without_wal_flag(mem.serialize()), int(version)
    finally:
        src.close()
        mem.close()


def create_backup(db_path: Path, master_key: bytes, passphrase: str) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise BackupError(f"パスフレーズは{MIN_PASSPHRASE_LEN}文字以上にしてください。")
    database, version = snapshot_database(db_path)
    payload = json.dumps(
        {
            "format": 1,
            "created_at": now_iso(),
            "schema_version": version,
            "master_key": base64.b64encode(master_key).decode("ascii"),
            "database": base64.b64encode(database).decode("ascii"),
        }
    ).encode("utf-8")
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    sealed = AESGCM(_derive(passphrase, salt)).encrypt(nonce, zlib.compress(payload), MAGIC)
    return MAGIC + salt + nonce + sealed


def read_backup(blob: bytes, passphrase: str) -> BackupContents:
    if len(blob) > MAX_BACKUP_BYTES:
        raise BackupError("バックアップファイルが大きすぎます。")
    header = len(MAGIC) + SALT_SIZE + NONCE_SIZE
    if len(blob) <= header or not blob.startswith(MAGIC):
        raise BackupError("このファイルはバックアップファイルではありません。")
    salt = blob[len(MAGIC):len(MAGIC) + SALT_SIZE]
    nonce = blob[len(MAGIC) + SALT_SIZE:header]
    try:
        payload = zlib.decompress(AESGCM(_derive(passphrase, salt)).decrypt(nonce, blob[header:], MAGIC))
        data = json.loads(payload)
        contents = BackupContents(
            master_key=base64.b64decode(data["master_key"]),
            database=base64.b64decode(data["database"]),
            created_at=str(data["created_at"]),
            schema_version=int(data["schema_version"]),
        )
    except InvalidTag as exc:
        raise BackupError("パスフレーズが違うか、ファイルが破損しています。") from exc
    except (zlib.error, ValueError, KeyError, TypeError) as exc:
        raise BackupError("バックアップファイルが破損しています。") from exc
    if len(contents.master_key) != 32:
        raise BackupError("バックアップファイルが破損しています。")
    return contents


def snapshot_setting(database: bytes, key: str) -> object:
    """スナップショット内の settings の値を読む（復元前の検証用）。"""
    mem = _open_snapshot(database)
    try:
        row = mem.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.DatabaseError as exc:
        raise BackupError("バックアップ内のデータベースが破損しています。") from exc
    finally:
        mem.close()
    return json.loads(row[0]) if row else None


def restore_database(db_path: Path, database: bytes) -> None:
    """スナップショットを検証してから、SQLite のバックアップAPIで現行DBへ書き戻す。"""
    mem = _open_snapshot(database)
    try:
        try:
            ok = mem.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise BackupError("バックアップ内のデータベースが破損しています。") from exc
        if ok != "ok":
            raise BackupError("バックアップ内のデータベースが破損しています。")
        dest = sqlite3.connect(db_path)
        try:
            mem.backup(dest)
        finally:
            dest.close()
    finally:
        mem.close()
