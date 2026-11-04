"""ユーザーが明示的に提供したプロフィール情報と同意記録。回答本文は暗号化して保存する。"""

from __future__ import annotations

import sqlite3

from app.crypto import Vault, is_encrypted
from app.db import Database, now_iso
from app.schemas import ProfileEntry

SOURCE_INITIAL_SETUP = "initial_setup"
SOURCE_USER_EDIT = "user_edit"
# 本人が自分で入力した情報なので確認済み・重要度は最大
EXPLICIT_IMPORTANCE = 10

_COLUMNS = "key, question, content, source, importance, confirmation_status, created_at, updated_at"


class ProfileRepository:
    def __init__(self, db: Database, vault: Vault) -> None:
        self.db = db
        self.vault = vault

    def list(self) -> list[ProfileEntry]:
        with self.db.transaction() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM profile_entries ORDER BY id").fetchall()
        return [ProfileEntry(**{**dict(row), "content": self.vault.decrypt(row["content"])}) for row in rows]

    def insert(self, conn: sqlite3.Connection, key: str, question: str | None, content: str) -> None:
        ts = now_iso()
        conn.execute(
            "INSERT INTO profile_entries (key, question, content, source, importance, confirmation_status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?)",
            (key, question, self.vault.encrypt(content), SOURCE_INITIAL_SETUP, EXPLICIT_IMPORTANCE, ts, ts),
        )

    def update_content(self, key: str, content: str) -> ProfileEntry | None:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "UPDATE profile_entries SET content = ?, source = ?, updated_at = ? WHERE key = ?",
                (self.vault.encrypt(content), SOURCE_USER_EDIT, now_iso(), key),
            )
            if cur.rowcount == 0:
                return None
        return next(e for e in self.list() if e.key == key)

    def upsert(self, key: str, question: str, content: str) -> ProfileEntry:
        """設定「あなたのこと」の項目。まだ無ければ追加し、あれば更新する。"""
        if self.update_content(key, content) is None:
            with self.db.transaction() as conn:
                ts = now_iso()
                conn.execute(
                    "INSERT INTO profile_entries (key, question, content, source, importance, confirmation_status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?)",
                    (key, question, self.vault.encrypt(content), SOURCE_USER_EDIT, EXPLICIT_IMPORTANCE, ts, ts),
                )
        return next(e for e in self.list() if e.key == key)

    def encrypt_legacy_rows(self) -> int:
        """Phase 1 で平文保存された回答を暗号化し直す。"""
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id, content FROM profile_entries").fetchall()
            legacy = [(self.vault.encrypt(r["content"]), r["id"]) for r in rows if not is_encrypted(r["content"])]
            conn.executemany("UPDATE profile_entries SET content = ? WHERE id = ?", legacy)
        return len(legacy)

    def record_consent(self, conn: sqlite3.Connection, kind: str, version: str, granted: bool) -> None:
        conn.execute(
            "INSERT INTO consents (kind, version, granted, granted_at) VALUES (?, ?, ?, ?)",
            (kind, version, int(granted), now_iso()),
        )
