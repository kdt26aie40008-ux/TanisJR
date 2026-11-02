"""基本設定の保存（settings テーブル、値は JSON）。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.db import Database, now_iso
from app.schemas import AppSettings

SETUP_COMPLETED_KEY = "setup_completed"


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self) -> AppSettings:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        stored = {row["key"]: json.loads(row["value"]) for row in rows}
        fields = AppSettings.model_fields
        return AppSettings(**{k: v for k, v in stored.items() if k in fields})

    def update(self, values: dict, conn: sqlite3.Connection | None = None) -> AppSettings:
        # 結合後の設定全体を検証してから保存する
        merged = AppSettings.model_validate({**self.get().model_dump(), **values})
        if conn is None:
            with self.db.transaction() as tx:
                self._write(tx, values)
        else:
            self._write(conn, values)
        return merged

    def is_setup_completed(self) -> bool:
        return bool(self.get_raw(SETUP_COMPLETED_KEY))

    def mark_setup_completed(self, conn: sqlite3.Connection) -> None:
        self._write(conn, {SETUP_COMPLETED_KEY: True})

    def get_raw(self, key: str) -> Any:
        """AppSettings に含まれない内部用の値（鍵の検証値など）を読む。"""
        with self.db.transaction() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_raw(self, key: str, value: Any) -> None:
        with self.db.transaction() as conn:
            self._write(conn, {key: value})

    @staticmethod
    def _write(conn: sqlite3.Connection, values: dict) -> None:
        ts = now_iso()
        conn.executemany(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            [(k, json.dumps(v, ensure_ascii=False), ts) for k, v in values.items()],
        )
