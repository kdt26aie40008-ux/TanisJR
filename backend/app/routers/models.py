"""モデルの状態確認と、ユーザー確認済みのダウンロード。"""

from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.deps import Services, get_services
from app.errors import AppError
from app.llm import catalog
from app.llm.ollama import OllamaError
from app.routers.sse import sse_response
from app.schemas import ModelPullRequest

router = APIRouter(prefix="/api/models", tags=["models"])


def ollama_models_dir() -> Path:
    """Ollama のモデル保存先（OLLAMA_MODELS 未設定時は既定の場所）。"""
    custom = os.environ.get("OLLAMA_MODELS")
    return Path(custom) if custom else Path.home() / ".ollama" / "models"


def free_space_gb(path: Path) -> float | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return round(shutil.disk_usage(probe).free / 1024**3, 1)
    except OSError:
        return None


def _installed(model: str, names: set[str]) -> bool:
    # タグ省略時は Ollama 上で ":latest" として登録される
    return model in names or (":" not in model and f"{model}:latest" in names)


@router.get("/status")
async def status(services: Services = Depends(get_services)) -> dict:
    settings = services.settings.get()
    storage = ollama_models_dir()
    result: dict[str, Any] = {
        "ollama_available": False,
        "message": None,
        "installed": [],
        "configured_model": settings.model,
        "configured_model_installed": False,
        "embedding_model": settings.embedding_model,
        "embedding_model_installed": False,
        "catalog": catalog.as_dicts(),
        # Ollama サービス側で別の保存先が設定されている場合は異なることがある
        "storage_path": str(storage),
        "free_space_gb": free_space_gb(storage),
    }
    try:
        models = await services.ollama.list_models()
    except OllamaError as exc:
        result["message"] = exc.message
        return result
    installed = [{"name": m.get("name", ""), "size_gb": round(m.get("size", 0) / 1024**3, 1)} for m in models]
    names = {m["name"] for m in installed}
    result.update(
        ollama_available=True,
        installed=installed,
        configured_model_installed=_installed(settings.model, names),
        embedding_model_installed=_installed(settings.embedding_model, names),
    )
    return result


@router.post("/pull")
async def pull(body: ModelPullRequest, services: Services = Depends(get_services)) -> StreamingResponse:
    if not body.confirmed:
        raise AppError(400, "confirmation_required", "ダウンロードの前に容量と保存先を確認してください。")
    if catalog.find(body.model) is None:
        raise AppError(400, "model_not_allowed", "このモデルはダウンロード対象として登録されていません。")

    async def events() -> AsyncIterator[dict[str, Any]]:
        try:
            async for chunk in services.ollama.pull(body.model):
                yield {
                    "type": "progress",
                    "status": chunk.get("status", ""),
                    "completed": chunk.get("completed"),
                    "total": chunk.get("total"),
                }
            yield {"type": "done", "model": body.model}
        except OllamaError as exc:
            yield {"type": "error", "code": exc.code, "message": exc.message}

    return sse_response(events())
