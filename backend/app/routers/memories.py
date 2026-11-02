"""記憶管理（一覧・検索・追加・修正・削除・承認・拒否）と会話履歴。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from app.deps import Services, get_services
from app.errors import AppError
from app.repositories.memories import STATUS_ACTIVE, STATUS_PENDING
from app.schemas import (
    ID_PATTERN,
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    Memory,
    MemoryCreate,
    MemoryUpdate,
)
from app.services.memory import InvalidMemoryState

router = APIRouter(prefix="/api", tags=["memories"])

MemoryId = Path(pattern=ID_PATTERN)


def _not_found() -> AppError:
    return AppError(404, "memory_not_found", "指定された記憶が見つかりません。")


def _with_titles(services: Services, items: list[Memory]) -> list[Memory]:
    titles = services.conversations.titles({m.source_conversation_id for m in items if m.source_conversation_id})
    return [m.model_copy(update={"source_conversation_title": titles.get(m.source_conversation_id or "")}) for m in items]


@router.get("/memories")
def list_memories(
    status: Literal["active", "pending"] | None = None,
    q: str = Query(default="", max_length=200),
    category: str = Query(default="", max_length=32),
    services: Services = Depends(get_services),
) -> list[Memory]:
    items = services.memories.list(status)
    if category:
        items = [m for m in items if m.category == category]
    needle = q.strip().casefold()
    if needle:
        # 内容は暗号化して保存しているため、復号後にアプリ内で検索する
        items = [m for m in items if needle in m.content.casefold() or needle in (m.source_excerpt or "").casefold()]
    return _with_titles(services, items)


@router.get("/memories/stats")
async def stats(services: Services = Depends(get_services)) -> dict:
    items = services.memories.list()
    settings = services.settings.get()
    return {
        "active": sum(m.status == STATUS_ACTIVE for m in items),
        "pending": sum(m.status == STATUS_PENDING for m in items),
        "unindexed": sum(m.status == STATUS_ACTIVE and not m.indexed for m in items),
        "embedding_model": settings.embedding_model,
        "embedding_available": await services.memory.embedding_available(),
    }


@router.post("/memories")
async def create_memory(body: MemoryCreate, services: Services = Depends(get_services)) -> Memory:
    return await services.memory.create_manual(body)


@router.put("/memories/{memory_id}")
async def update_memory(body: MemoryUpdate, memory_id: str = MemoryId, services: Services = Depends(get_services)) -> Memory:
    updated = await services.memory.update(memory_id, body)
    if updated is None:
        raise _not_found()
    return _with_titles(services, [updated])[0]


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str = MemoryId, services: Services = Depends(get_services)) -> dict:
    if not services.memory.delete(memory_id):
        raise _not_found()
    return {"deleted": True}


@router.post("/memories/{memory_id}/approve")
async def approve_memory(
    body: MemoryUpdate | None = None, memory_id: str = MemoryId, services: Services = Depends(get_services)
) -> Memory:
    try:
        approved = await services.memory.approve(memory_id, body)
    except InvalidMemoryState as exc:
        raise AppError(409, "not_pending", str(exc)) from exc
    if approved is None:
        raise _not_found()
    return approved


@router.post("/memories/{memory_id}/reject")
def reject_memory(memory_id: str = MemoryId, services: Services = Depends(get_services)) -> dict:
    # 拒否された情報は保持せず削除する
    try:
        deleted = services.memory.delete(memory_id, pending_only=True)
    except InvalidMemoryState as exc:
        raise AppError(409, "not_pending", str(exc)) from exc
    if not deleted:
        raise _not_found()
    return {"deleted": True}


@router.post("/memories/reindex")
async def reindex(services: Services = Depends(get_services)) -> dict:
    return await services.memory.reconcile()


# ===== 会話履歴 =====


@router.get("/conversations")
def list_conversations(services: Services = Depends(get_services)) -> list[ConversationSummary]:
    return services.conversations.list()


@router.post("/conversations")
def create_conversation(body: ConversationCreate, services: Services = Depends(get_services)) -> ConversationSummary:
    if not services.settings.is_setup_completed():
        raise AppError(409, "setup_required", "初回設定が完了していません。")
    conversation_id = services.conversations.create(body.messages)
    detail = services.conversations.get(conversation_id)
    assert detail is not None
    return ConversationSummary(**detail.model_dump(exclude={"messages"}))


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str = Path(pattern=ID_PATTERN), services: Services = Depends(get_services)
) -> ConversationDetail:
    detail = services.conversations.get(conversation_id)
    if detail is None:
        raise AppError(404, "conversation_not_found", "指定された会話が見つかりません。")
    return detail


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str = Path(pattern=ID_PATTERN),
    delete_memories: bool = False,
    services: Services = Depends(get_services),
) -> dict:
    if not services.memory.delete_conversation(conversation_id, delete_memories):
        raise AppError(404, "conversation_not_found", "指定された会話が見つかりません。")
    return {"deleted": True}
