from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.deps import Services, get_services
from app.llm.ollama import OllamaError

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(services: Services = Depends(get_services)) -> dict:
    ollama: dict = {"available": False, "version": None, "message": None}
    try:
        ollama["version"] = await services.ollama.version()
        ollama["available"] = True
    except OllamaError as exc:
        ollama["message"] = exc.message
    return {
        "status": "ok",
        "version": __version__,
        "ollama": ollama,
        "data_locked": services.vault.locked,
        "locked_reason": services.vault.locked_reason,
    }
