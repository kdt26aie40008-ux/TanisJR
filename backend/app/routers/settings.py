from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from app.deps import Services, get_services
from app.errors import AppError, setup_required
from app.schemas import AppSettings, ProfileEntry, ProfileUpdate, SettingsUpdate

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def get_settings(services: Services = Depends(get_services)) -> AppSettings:
    return services.settings.get()


@router.put("/settings")
def update_settings(
    body: SettingsUpdate, background: BackgroundTasks, services: Services = Depends(get_services)
) -> AppSettings:
    values = body.model_dump(exclude_none=True)
    if not values:
        raise AppError(400, "no_changes", "変更する項目がありません。")
    previous = services.settings.get()
    updated = services.settings.update(values)
    if updated.embedding_model != previous.embedding_model and not services.vault.locked:
        # 埋め込みモデルが変わったら新しいモデルで索引を作り直す
        background.add_task(services.memory.reconcile)
    return updated


@router.get("/profile")
def get_profile(services: Services = Depends(get_services)) -> list[ProfileEntry]:
    return services.profile.list()


@router.put("/profile")
def update_profile(body: ProfileUpdate, services: Services = Depends(get_services)) -> ProfileEntry:
    if not services.settings.is_setup_completed():
        raise setup_required()
    entry = services.profile.update_content(body.key, body.content)
    if entry is None:
        raise AppError(404, "profile_not_found", "指定されたプロフィール項目が見つかりません。")
    return entry
