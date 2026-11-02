"""追加学習用データ（記憶種別5: 承認済み学習データ）。

- 保存を許可した会話・手動入力・蒸留（教師モデルの回答）から作られ、必ず「承認待ち」から始まる。
- 学習に使うのは承認済みのものだけ。本文は暗号化して保存する。
- 重複判定用の指紋は、鍵付きハッシュ（HMAC）にして本文を推測できないようにする。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.crypto import Vault
from app.db import Database, now_iso
from app.repositories.conversations import ConversationRepository
from app.schemas import clean_text

Source = Literal["conversation", "manual", "distill"]
Status = Literal["pending", "approved", "rejected"]

MIN_CHARS = 2
MAX_USER_CHARS = 2000
MAX_ASSISTANT_CHARS = 4000

_PII_PATTERNS = {
    "電話番号": re.compile(r"0\d{1,4}-?\d{1,4}-?\d{3,4}"),
    "メールアドレス": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "郵便番号": re.compile(r"〒?\d{3}-\d{4}"),
    "カード番号らしき数字": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


class TrainingExample(BaseModel):
    id: str
    source: Source
    conversation_id: str | None
    user_text: str
    assistant_text: str
    status: Status
    created_at: str
    updated_at: str
    warnings: list[str] = []


class ExampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_text: str = Field(min_length=1, max_length=MAX_USER_CHARS)
    assistant_text: str = Field(min_length=1, max_length=MAX_ASSISTANT_CHARS)

    @field_validator("user_text", "assistant_text")
    @classmethod
    def _clean(cls, value: str) -> str:
        value = clean_text(value)
        if not value:
            raise ValueError("内容を入力してください。")
        return value


class ExampleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_text: str | None = Field(default=None, min_length=1, max_length=MAX_USER_CHARS)
    assistant_text: str | None = Field(default=None, min_length=1, max_length=MAX_ASSISTANT_CHARS)

    @field_validator("user_text", "assistant_text")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value) or None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s、。,.!！?？「」『』()（）]", "", text)


def quality_warnings(user_text: str, assistant_text: str) -> list[str]:
    warnings: list[str] = []
    if len(normalize(user_text)) < MIN_CHARS or len(normalize(assistant_text)) < MIN_CHARS:
        warnings.append("短すぎます（学習効果がほとんどありません）")
    if len(assistant_text) > 2000:
        warnings.append("応答が長すぎます（学習時に切り詰められる可能性があります）")
    for label, pattern in _PII_PATTERNS.items():
        if pattern.search(user_text) or pattern.search(assistant_text):
            warnings.append(f"{label}が含まれている可能性があります")
    if "<think>" in assistant_text:
        warnings.append("思考過程のタグが含まれています")
    return warnings


class TrainingDataRepository:
    def __init__(self, db: Database, vault: Vault, conversations: ConversationRepository) -> None:
        self.db = db
        self.vault = vault
        self.conversations = conversations

    def _fingerprint(self, user_text: str, assistant_text: str) -> str:
        message = f"{normalize(user_text)}\x00{normalize(assistant_text)}".encode()
        return hmac.new(self.vault.cipher.key, message, hashlib.sha256).hexdigest()

    def _exists(self, fingerprint: str) -> bool:
        with self.db.transaction() as conn:
            return conn.execute(
                "SELECT 1 FROM training_examples WHERE fingerprint = ? AND status != 'rejected'", (fingerprint,)
            ).fetchone() is not None

    def add(self, user_text: str, assistant_text: str, source: Source, conversation_id: str | None = None) -> TrainingExample | None:
        """承認待ちとして追加する。同じ内容がすでにあれば追加しない。"""
        fingerprint = self._fingerprint(user_text, assistant_text)
        if self._exists(fingerprint):
            return None
        example_id = uuid.uuid4().hex
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO training_examples (id, source, conversation_id, user_text, assistant_text, status, fingerprint, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (example_id, source, conversation_id, self.vault.encrypt(user_text), self.vault.encrypt(assistant_text), fingerprint, ts, ts),
            )
        return self.get(example_id)

    def add_from_conversation(self, conversation_id: str) -> list[TrainingExample]:
        """保存された会話の各往復（ユーザー発言→AI応答）を候補にする。"""
        detail = self.conversations.get(conversation_id)
        if detail is None:
            raise KeyError(conversation_id)
        created: list[TrainingExample] = []
        msgs = detail.messages
        for prev, cur in zip(msgs, msgs[1:]):
            if prev.role == "user" and cur.role == "assistant":
                ex = self.add(prev.content[:MAX_USER_CHARS], cur.content[:MAX_ASSISTANT_CHARS], "conversation", conversation_id)
                if ex:
                    created.append(ex)
        return created

    def get(self, example_id: str) -> TrainingExample | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM training_examples WHERE id = ?", (example_id,)).fetchone()
        return self._to_model(row) if row else None

    def list(self, status: str | None = None) -> list[TrainingExample]:
        sql, params = "SELECT * FROM training_examples", ()
        if status:
            sql, params = sql + " WHERE status = ?", (status,)
        with self.db.transaction() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC, rowid DESC", params).fetchall()
        return [self._to_model(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM training_examples GROUP BY status").fetchall()
        result = {"pending": 0, "approved": 0, "rejected": 0}
        result.update({r["status"]: r["n"] for r in rows})
        return result

    def update(self, example_id: str, changes: ExampleUpdate) -> TrainingExample | None:
        current = self.get(example_id)
        if current is None:
            return None
        user_text = changes.user_text or current.user_text
        assistant_text = changes.assistant_text or current.assistant_text
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE training_examples SET user_text = ?, assistant_text = ?, fingerprint = ?, updated_at = ? WHERE id = ?",
                (self.vault.encrypt(user_text), self.vault.encrypt(assistant_text), self._fingerprint(user_text, assistant_text), now_iso(), example_id),
            )
        return self.get(example_id)

    def set_status(self, example_id: str, status: Status) -> TrainingExample | None:
        with self.db.transaction() as conn:
            if conn.execute(
                "UPDATE training_examples SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), example_id)
            ).rowcount == 0:
                return None
        return self.get(example_id)

    def delete(self, example_id: str) -> bool:
        with self.db.transaction() as conn:
            return conn.execute("DELETE FROM training_examples WHERE id = ?", (example_id,)).rowcount > 0

    def dedupe(self) -> int:
        """内容が同じものを1件にまとめる（承認済みを優先して残す）。"""
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, fingerprint, status FROM training_examples WHERE status != 'rejected' "
                "ORDER BY CASE status WHEN 'approved' THEN 0 ELSE 1 END, created_at"
            ).fetchall()
            seen: set[str] = set()
            removed = []
            for r in rows:
                if r["fingerprint"] in seen:
                    removed.append(r["id"])
                else:
                    seen.add(r["fingerprint"])
            conn.executemany("DELETE FROM training_examples WHERE id = ?", [(i,) for i in removed])
        return len(removed)

    def approved_pairs(self) -> list[tuple[str, str]]:
        return [(e.user_text, e.assistant_text) for e in self.list("approved")]

    def export_jsonl(self, system_prompt: str) -> str:
        """承認済みデータを chat 形式の JSONL にする（学習・持ち出し用。平文になる）。"""
        lines = [
            json.dumps(
                {"messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ]},
                ensure_ascii=False,
            )
            for user, assistant in self.approved_pairs()
        ]
        return "\n".join(lines) + ("\n" if lines else "")

    def _to_model(self, row: object) -> TrainingExample:
        data = dict(row)  # type: ignore[call-overload]
        data.pop("fingerprint")
        data["user_text"] = self.vault.decrypt(data["user_text"])
        data["assistant_text"] = self.vault.decrypt(data["assistant_text"])
        data["warnings"] = quality_warnings(data["user_text"], data["assistant_text"])
        return TrainingExample(**data)
