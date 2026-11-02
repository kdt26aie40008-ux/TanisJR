"""保存を許可された会話の履歴。タイトルと本文は暗号化して保存する。"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Sequence

from app.crypto import Vault
from app.db import Database, now_iso
from app.schemas import ChatMessage, ConversationDetail, ConversationSummary, StoredMessage

TITLE_LEN = 30


def make_title(messages: Sequence[ChatMessage]) -> str:
    first = next((m.content for m in messages if m.role == "user"), "")
    title = " ".join(first.split())
    return (title[:TITLE_LEN] + "…") if len(title) > TITLE_LEN else (title or "新しい会話")


class ConversationRepository:
    def __init__(self, db: Database, vault: Vault) -> None:
        self.db = db
        self.vault = vault

    def create(self, messages: Sequence[ChatMessage]) -> str:
        conversation_id = uuid.uuid4().hex
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, self.vault.encrypt(make_title(messages)), ts, ts),
            )
            for m in messages:
                self._insert_message(conn, conversation_id, m.role, m.content, ts)
        return conversation_id

    def exists(self, conversation_id: str) -> bool:
        with self.db.transaction() as conn:
            return conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone() is not None

    def append_turn(self, conversation_id: str, user_text: str, assistant_text: str) -> int:
        """1往復を保存し、ユーザー発言のメッセージIDを返す。"""
        ts = now_iso()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT title, (SELECT COUNT(*) FROM messages WHERE conversation_id = ?) AS n FROM conversations WHERE id = ?",
                               (conversation_id, conversation_id)).fetchone()
            if row is None:
                raise KeyError(conversation_id)
            user_id = self._insert_message(conn, conversation_id, "user", user_text, ts)
            self._insert_message(conn, conversation_id, "assistant", assistant_text, ts)
            updates = {"updated_at": ts}
            if row["n"] == 0:
                updates["title"] = self.vault.encrypt(make_title([ChatMessage(role="user", content=user_text)]))
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE conversations SET {sets} WHERE id = ?", (*updates.values(), conversation_id))
        return user_id

    def list(self) -> list[ConversationSummary]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count "
                "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
                "GROUP BY c.id ORDER BY c.updated_at DESC, c.rowid DESC"
            ).fetchall()
        return [ConversationSummary(**{**dict(r), "title": self.vault.decrypt(r["title"])}) for r in rows]

    def titles(self, ids: set[str]) -> dict[str, str]:
        if not ids:
            return {}
        with self.db.transaction() as conn:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(f"SELECT id, title FROM conversations WHERE id IN ({marks})", tuple(ids)).fetchall()
        return {r["id"]: self.vault.decrypt(r["title"]) for r in rows}

    def get(self, conversation_id: str) -> ConversationDetail | None:
        summary = next((c for c in self.list() if c.id == conversation_id), None)
        if summary is None:
            return None
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        messages = [StoredMessage(**{**dict(r), "content": self.vault.decrypt(r["content"])}) for r in rows]
        return ConversationDetail(**summary.model_dump(), messages=messages)

    def delete(self, conn: sqlite3.Connection, conversation_id: str) -> bool:
        return conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount > 0

    def _insert_message(self, conn: sqlite3.Connection, conversation_id: str, role: str, content: str, ts: str) -> int:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, self.vault.encrypt(content), ts),
        )
        return int(cur.lastrowid)
