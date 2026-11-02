"""SQLite 接続とマイグレーション。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

# 連番で追加していく。既存の番号の内容は変更しないこと。
MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE profile_entries (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        key                 TEXT NOT NULL UNIQUE,
        question            TEXT,
        content             TEXT NOT NULL,
        source              TEXT NOT NULL,
        importance          INTEGER NOT NULL DEFAULT 5,
        confirmation_status TEXT NOT NULL DEFAULT 'confirmed',
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    );
    CREATE TABLE consents (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL,
        version    TEXT NOT NULL,
        granted    INTEGER NOT NULL,
        granted_at TEXT NOT NULL
    );
    """,
    2: """
    CREATE TABLE conversations (
        id         TEXT PRIMARY KEY,
        title      TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE messages (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content         TEXT NOT NULL,
        created_at      TEXT NOT NULL
    );
    CREATE INDEX idx_messages_conversation ON messages(conversation_id, id);
    CREATE TABLE memories (
        id                     TEXT PRIMARY KEY,
        category               TEXT NOT NULL,
        content                TEXT NOT NULL,
        source_type            TEXT NOT NULL,
        source_conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
        source_message_id      INTEGER,
        source_excerpt         TEXT,
        importance             INTEGER NOT NULL,
        sensitivity            TEXT NOT NULL,
        status                 TEXT NOT NULL,
        confirmation_status    TEXT NOT NULL,
        indexed_model          TEXT,
        created_at             TEXT NOT NULL,
        updated_at             TEXT NOT NULL
    );
    CREATE INDEX idx_memories_status ON memories(status);
    CREATE INDEX idx_memories_source ON memories(source_conversation_id);
    """,
    3: """
    CREATE TABLE avatars (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        size           INTEGER NOT NULL,
        is_placeholder INTEGER NOT NULL DEFAULT 0,
        vrm_version    TEXT NOT NULL,
        meta           TEXT NOT NULL,
        created_at     TEXT NOT NULL
    );
    """,
    4: """
    CREATE TABLE calendar_operations (
        id              TEXT PRIMARY KEY,
        action          TEXT NOT NULL CHECK (action IN ('create', 'update', 'delete')),
        event_id        TEXT,
        draft           TEXT,
        target          TEXT,
        source          TEXT NOT NULL,
        status          TEXT NOT NULL,
        error           TEXT,
        result_event_id TEXT,
        created_at      TEXT NOT NULL,
        decided_at      TEXT
    );
    CREATE INDEX idx_calendar_operations_status ON calendar_operations(status);
    CREATE TABLE calendar_cache (
        event_id   TEXT PRIMARY KEY,
        event      TEXT NOT NULL,
        starts_at  TEXT NOT NULL,
        synced_at  TEXT NOT NULL
    );
    CREATE TABLE event_notify (
        event_id   TEXT PRIMARY KEY,
        minutes    INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE notifications_sent (
        key     TEXT PRIMARY KEY,
        sent_at TEXT NOT NULL
    );
    """,
    5: """
    CREATE TABLE training_examples (
        id              TEXT PRIMARY KEY,
        source          TEXT NOT NULL,
        conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
        user_text       TEXT NOT NULL,
        assistant_text  TEXT NOT NULL,
        status          TEXT NOT NULL,
        fingerprint     TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );
    CREATE INDEX idx_training_examples_status ON training_examples(status);
    CREATE INDEX idx_training_examples_fingerprint ON training_examples(fingerprint);
    CREATE TABLE training_runs (
        id            TEXT PRIMARY KEY,
        base          TEXT NOT NULL,
        status        TEXT NOT NULL,
        example_count INTEGER NOT NULL,
        params        TEXT NOT NULL,
        metrics       TEXT,
        error         TEXT,
        ollama_model  TEXT,
        created_at    TEXT NOT NULL,
        started_at    TEXT,
        finished_at   TEXT
    );
    """,
}

LATEST_VERSION = max(MIGRATIONS)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        # 削除したデータがファイル上に残りにくくする
        conn.execute("PRAGMA secure_delete = ON")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as conn:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            for version in sorted(v for v in MIGRATIONS if v > current):
                conn.executescript(MIGRATIONS[version])
                conn.execute(f"PRAGMA user_version = {int(version)}")
