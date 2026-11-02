"""記憶の登録・承認・削除・検索。SQLite と ChromaDB の整合性はここで保つ。

- ChromaDB に入るのは status=active の記憶だけ（承認待ちは RAG に使わない）。
- 削除は SQLite のトランザクション内で ChromaDB からも削除し、失敗したらロールバックする。
- 埋め込みモデルが使えない場合も記憶は SQLite に保存し、後で reconcile() で索引に追加する。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

from app.db import Database
from app.llm.ollama import OllamaClient, OllamaError
from app.repositories.conversations import ConversationRepository
from app.repositories.memories import (
    SENSITIVITY_GENERAL,
    SENSITIVITY_IMPORTANT,
    SOURCE_CONVERSATION,
    SOURCE_USER_MANUAL,
    STATUS_ACTIVE,
    STATUS_PENDING,
    MemoryRepository,
    NewMemory,
)
from app.repositories.settings import SettingsRepository
from app.schemas import IMPORTANT_CATEGORIES, Memory, MemoryCreate, MemoryUpdate
from app.services.extraction import extract_candidates
from app.vector_index import VectorIndex

logger = logging.getLogger(__name__)

# qwen3-embedding は検索クエリに指示文を付けると精度が上がる
QUERY_INSTRUCTION = "Instruct: ユーザーの発言に関連する、ユーザー本人についての記憶を検索する\nQuery: "
# これより近い既存の記憶があれば重複とみなす（cosine 距離）
DUPLICATE_DISTANCE = 0.15
INDEX_BATCH = 32


class InvalidMemoryState(Exception):
    pass


# LLM の分類漏れに備えた安全策: 個人情報・影響の大きい話題を含む記憶は必ず承認待ちにする
_SENSITIVE_PATTERN = re.compile(
    "|".join(
        [
            r"住んで|在住|住所|出身|実家|最寄り",
            r"電話|メール|アドレス|連絡先|LINE|アカウント",
            r"\d+\s*歳|年齢|誕生日|生年月日",
            r"勤務|勤め|会社|職場|上司|同僚|年収|給料|収入|借金|ローン|貯金",
            r"学校|大学|高校|学部|クラス",
            r"病|通院|入院|薬|症状|障害|診断|メンタル|うつ",
            r"家族|父|母|妻|夫|息子|娘|子ども|子供|兄|姉|弟|妹|恋人|彼氏|彼女|離婚|結婚",
            r"宗教|政治|支持政党",
        ]
    )
)


def is_important(category: str, importance: int, sensitive: bool = False, content: str = "") -> bool:
    """本人の確認が必要な重要情報か。

    importance は「会話での有用度」なので判定に使わない（`importance` 引数は互換のため残す）。
    """
    return sensitive or category in IMPORTANT_CATEGORIES or bool(_SENSITIVE_PATTERN.search(content))


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s、。,.!！?？「」『』()（）]", "", text)


@dataclass(frozen=True)
class RelevantMemory:
    memory: Memory
    distance: float


class MemoryService:
    def __init__(
        self,
        db: Database,
        memories: MemoryRepository,
        conversations: ConversationRepository,
        settings: SettingsRepository,
        ollama: OllamaClient,
        index: VectorIndex,
    ) -> None:
        self.db = db
        self.memories = memories
        self.conversations = conversations
        self.settings = settings
        self.ollama = ollama
        self.index = index

    # ---------- 埋め込み ----------

    async def _embed(self, model: str, texts: list[str]) -> list[list[float]] | None:
        try:
            return await self.ollama.embed(model, texts)
        except OllamaError as exc:
            logger.warning("Embedding unavailable (%s): %s", exc.code, exc.detail)
            return None

    async def embedding_available(self) -> bool:
        model = self.settings.get().embedding_model
        try:
            names = {m.get("name") for m in await self.ollama.list_models()}
        except OllamaError:
            return False
        return model in names or (":" not in model and f"{model}:latest" in names)

    async def _index(self, items: list[Memory], vectors: list[list[float]] | None = None) -> int:
        items = [m for m in items if m.status == STATUS_ACTIVE]
        if not items:
            return 0
        model = self.settings.get().embedding_model
        if vectors is None:
            vectors = await self._embed(model, [m.content for m in items])
            if vectors is None:
                return 0
        ids = [m.id for m in items]
        self.index.upsert(model, ids, vectors)
        self.memories.set_indexed(ids, model)
        return len(ids)

    # ---------- 登録・更新 ----------

    async def _add(self, new: NewMemory, vector: list[float] | None = None) -> Memory:
        with self.db.transaction() as conn:
            memory_id = self.memories.insert(conn, new)
        memory = self.memories.get(memory_id)
        assert memory is not None
        if memory.status == STATUS_ACTIVE:
            await self._index([memory], None if vector is None else [vector])
        return self.memories.get(memory_id) or memory

    async def create_manual(self, body: MemoryCreate) -> Memory:
        # 本人が直接入力した情報は確認済みとして扱う
        important = is_important(body.category, body.importance, content=body.content)
        return await self._add(
            NewMemory(
                category=body.category,
                content=body.content,
                source_type=SOURCE_USER_MANUAL,
                importance=body.importance,
                sensitivity=SENSITIVITY_IMPORTANT if important else SENSITIVITY_GENERAL,
                status=STATUS_ACTIVE,
                confirmation_status="confirmed",
            )
        )

    async def update(self, memory_id: str, changes: MemoryUpdate) -> Memory | None:
        current = self.memories.get(memory_id)
        if current is None:
            return None
        fields: dict[str, object] = changes.model_dump(exclude_none=True)
        if not fields:
            return current
        category = str(fields.get("category", current.category))
        importance = int(fields.get("importance", current.importance))  # type: ignore[arg-type]
        content = str(fields.get("content", current.content))
        if is_important(category, importance, content=content) or current.sensitivity == SENSITIVITY_IMPORTANT:
            fields["sensitivity"] = SENSITIVITY_IMPORTANT
        if current.status == STATUS_ACTIVE:
            # 本人が内容を確認・修正したので確認済みにする
            fields["confirmation_status"] = "confirmed"
        content_changed = "content" in fields and fields["content"] != current.content
        if content_changed:
            fields["indexed_model"] = None
        with self.db.transaction() as conn:
            self.memories.update(conn, memory_id, **fields)
        updated = self.memories.get(memory_id)
        if updated and content_changed:
            await self._index([updated])
        return self.memories.get(memory_id)

    async def approve(self, memory_id: str, changes: MemoryUpdate | None = None) -> Memory | None:
        current = self.memories.get(memory_id)
        if current is None:
            return None
        if current.status != STATUS_PENDING:
            raise InvalidMemoryState("この記憶は承認待ちではありません。")
        fields: dict[str, object] = changes.model_dump(exclude_none=True) if changes else {}
        fields.update(status=STATUS_ACTIVE, confirmation_status="confirmed", indexed_model=None)
        with self.db.transaction() as conn:
            self.memories.update(conn, memory_id, **fields)
        approved = self.memories.get(memory_id)
        assert approved is not None
        await self._index([approved])
        return self.memories.get(memory_id)

    # ---------- 削除（SQLite と ChromaDB の両方） ----------

    def delete(self, memory_id: str, *, pending_only: bool = False) -> bool:
        current = self.memories.get(memory_id)
        if current is None:
            return False
        if pending_only and current.status != STATUS_PENDING:
            raise InvalidMemoryState("この記憶は承認待ちではありません。")
        with self.db.transaction() as conn:
            self.memories.delete(conn, memory_id)
            # 索引の削除に失敗した場合は例外でトランザクションごと取り消す
            self.index.delete([memory_id])
        return True

    def delete_conversation(self, conversation_id: str, delete_memories: bool) -> bool:
        with self.db.transaction() as conn:
            ids = self.memories.ids_from_conversation(conn, conversation_id) if delete_memories else []
            for memory_id in ids:
                self.memories.delete(conn, memory_id)
            if not self.conversations.delete(conn, conversation_id):
                return False
            self.index.delete(ids)
        return True

    # ---------- 整合性 ----------

    async def reconcile(self) -> dict[str, int]:
        """ChromaDB 側の孤立したIDを削除し、未索引の記憶を索引に追加する。"""
        model = self.settings.get().embedding_model
        indexed = self.index.ids(model)
        active = self.memories.active_ids()
        orphans = sorted(indexed - active)
        self.index.delete(orphans)
        # 索引済みの印があるのに実際には無いもの（ChromaDB の削除・破損など）は印を外す
        missing = sorted(active - indexed)
        self.memories.set_indexed(missing, None)
        added = 0
        pending = self.memories.unindexed_active(model)
        for start in range(0, len(pending), INDEX_BATCH):
            done = await self._index(pending[start:start + INDEX_BATCH])
            if done == 0:
                break
            added += done
        return {"removed_orphans": len(orphans), "indexed": added, "unindexed": len(pending) - added}

    # ---------- 検索 (RAG) ----------

    async def relevant(self, text: str) -> tuple[list[RelevantMemory], str | None]:
        """関連する記憶と、利用者に伝えるべき注意（埋め込みが使えない等）を返す。"""
        settings = self.settings.get()
        model = settings.embedding_model
        if settings.rag_max_results == 0:
            return [], None
        if self.index.count(model) == 0:
            if self.memories.active_ids():
                return [], "記憶の検索索引がまだ作成されていないため、記憶を参照せずに応答しています。"
            return [], None
        vectors = await self._embed(model, [QUERY_INSTRUCTION + text])
        if vectors is None:
            return [], f"記憶検索用モデル「{model}」が使えないため、記憶を参照せずに応答しています。"
        hits = self.index.query(model, vectors[0], settings.rag_max_results * 2)
        close = [(i, d) for i, d in hits if d <= settings.rag_max_distance][: settings.rag_max_results]
        found = self.memories.get_many([i for i, _ in close])
        # 索引に残っていても SQLite で有効でないものは使わない
        return [RelevantMemory(found[i], d) for i, d in close if i in found and found[i].status == STATUS_ACTIVE], None

    # ---------- 会話からの抽出 ----------

    async def process_exchange(
        self, conversation_id: str, message_id: int, user_text: str, previous_assistant: str | None
    ) -> list[Memory]:
        settings = self.settings.get()
        if not settings.auto_extract:
            return []
        try:
            candidates = await extract_candidates(self.ollama, settings.model, user_text, previous_assistant)
        except OllamaError as exc:
            logger.warning("Memory extraction failed (%s)", exc.code)
            return []
        if not candidates:
            return []

        known = {_normalize(m.content) for m in self.memories.list()}
        vectors = await self._embed(settings.embedding_model, [c.content for c in candidates])
        created: list[Memory] = []
        for i, c in enumerate(candidates):
            if _normalize(c.content) in known:
                continue
            vector = vectors[i] if vectors else None
            if vector is not None and self.index.count(settings.embedding_model):
                nearest = self.index.query(settings.embedding_model, vector, 1)
                if nearest and nearest[0][1] < DUPLICATE_DISTANCE:
                    continue
            important = is_important(c.category, c.importance, c.sensitive, c.content)
            memory = await self._add(
                NewMemory(
                    category=c.category,
                    content=c.content,
                    source_type=SOURCE_CONVERSATION,
                    importance=c.importance,
                    sensitivity=SENSITIVITY_IMPORTANT if important else SENSITIVITY_GENERAL,
                    # 重要情報は本人の承認があるまで会話に使わない
                    status=STATUS_PENDING if important else STATUS_ACTIVE,
                    confirmation_status="pending" if important else "auto",
                    source_conversation_id=conversation_id,
                    source_message_id=message_id,
                    source_excerpt=user_text[:500],
                ),
                vector=None if important else vector,
            )
            known.add(_normalize(c.content))
            created.append(memory)
        return created
