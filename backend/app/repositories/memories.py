"""記憶（会話から抽出したもの・手動追加したもの）。内容と出典抜粋は暗号化して保存する。

ベクトル索引との整合性は services/memory.py が管理する。このクラスは SQLite のみを扱う。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from app.crypto import Vault
from app.db import Database, now_iso
from app.schemas import Memory

STATUS_ACTIVE = "active"
STATUS_PENDING = "pending"
SENSITIVITY_GENERAL = "general"
SENSITIVITY_IMPORTANT = "important"
SOURCE_CONVERSATION = "conversation"
SOURCE_USER_MANUAL = "user_manual"


@dataclass(frozen=True)
class NewMemory:
    category: str
    content: str
    source_type: str
    importance: int
    sensitivity: str
    status: str
    confirmation_status: str
    source_conversation_id: str | None = None
    source_message_id: int | None = None
    source_excerpt: str | None = None


class MemoryRepository:
    def __init__(self, db: Database, vault: Vault) -> None:
        self.db = db
        self.vault = vault

    def insert(self, conn: sqlite3.Connection, new: NewMemory) -> str:
        memory_id = uuid.uuid4().hex
        ts = now_iso()
        conn.execute(
            "INSERT INTO memories (id, category, content, source_type, source_conversation_id, source_message_id, "
            "source_excerpt, importance, sensitivity, status, confirmation_status, indexed_model, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                memory_id,
                new.category,
                self.vault.encrypt(new.content),
                new.source_type,
                new.source_conversation_id,
                new.source_message_id,
                None if new.source_excerpt is None else self.vault.encrypt(new.source_excerpt),
                new.importance,
                new.sensitivity,
                new.status,
                new.confirmation_status,
                ts,
                ts,
            ),
        )
        return memory_id

    def list(self, status: str | None = None) -> list[Memory]:
        sql = "SELECT * FROM memories"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        with self.db.transaction() as conn:
            rows = conn.execute(sql + " ORDER BY updated_at DESC, rowid DESC", params).fetchall()
        return [self._to_model(r) for r in rows]

    def get(self, memory_id: str) -> Memory | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._to_model(row) if row else None

    def get_many(self, ids: list[str]) -> dict[str, Memory]:
        if not ids:
            return {}
        with self.db.transaction() as conn:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(f"SELECT * FROM memories WHERE id IN ({marks})", tuple(ids)).fetchall()
        return {r["id"]: self._to_model(r) for r in rows}

    def update(self, conn: sqlite3.Connection, memory_id: str, **fields: object) -> bool:
        if "content" in fields:
            fields["content"] = self.vault.encrypt(str(fields["content"]))
        fields["updated_at"] = now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        return conn.execute(f"UPDATE memories SET {sets} WHERE id = ?", (*fields.values(), memory_id)).rowcount > 0

    def set_indexed(self, ids: list[str], model: str | None) -> None:
        with self.db.transaction() as conn:
            conn.executemany("UPDATE memories SET indexed_model = ? WHERE id = ?", [(model, i) for i in ids])

    def delete(self, conn: sqlite3.Connection, memory_id: str) -> bool:
        return conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount > 0

    def ids_from_conversation(self, conn: sqlite3.Connection, conversation_id: str) -> list[str]:
        rows = conn.execute("SELECT id FROM memories WHERE source_conversation_id = ?", (conversation_id,)).fetchall()
        return [r["id"] for r in rows]

    def active_ids(self) -> set[str]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id FROM memories WHERE status = ?", (STATUS_ACTIVE,)).fetchall()
        return {r["id"] for r in rows}

    def unindexed_active(self, model: str) -> list[Memory]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE status = ? AND (indexed_model IS NULL OR indexed_model != ?)",
                (STATUS_ACTIVE, model),
            ).fetchall()
        return [self._to_model(r) for r in rows]

    def clear_index_marks(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE memories SET indexed_model = NULL")

    def _to_model(self, row: sqlite3.Row) -> Memory:
        data = dict(row)
        data["content"] = self.vault.decrypt(data["content"])
        data["source_excerpt"] = self.vault.decrypt_opt(data["source_excerpt"])
        data["indexed"] = data.pop("indexed_model") is not None
        data.pop("source_message_id", None)
        return Memory(**data)
