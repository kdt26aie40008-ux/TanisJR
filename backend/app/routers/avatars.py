"""VRM アバターの登録・一覧・配信・削除・選択。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import FileResponse

from app.avatars import MAX_AVATAR_BYTES, Avatar, AvatarError
from app.deps import Services, get_services
from app.errors import AppError
from app.routers.speech import read_limited
from app.schemas import ID_PATTERN, AvatarUpdate

router = APIRouter(prefix="/api/avatars", tags=["avatars"])

AvatarId = Path(pattern=ID_PATTERN)


def _not_found() -> AppError:
    return AppError(404, "avatar_not_found", "指定されたアバターが見つかりません。")


@router.get("")
def list_avatars(services: Services = Depends(get_services)) -> dict:
    return {"avatars": services.avatars.list(), "active_id": services.settings.get().avatar_id or None}


@router.post("")
async def upload(
    request: Request,
    name: str = Query(default="", max_length=64),
    placeholder: bool = False,
    services: Services = Depends(get_services),
) -> Avatar:
    data = await read_limited(request, MAX_AVATAR_BYTES)
    try:
        avatar = services.avatars.add(data, name, placeholder)
    except AvatarError as exc:
        raise AppError(exc.status, "invalid_avatar", exc.message) from exc
    # 最初のアバターは自動で選択する
    if not services.settings.get().avatar_id:
        services.settings.update({"avatar_id": avatar.id})
    return avatar


@router.get("/{avatar_id}/file")
def avatar_file(avatar_id: str = AvatarId, services: Services = Depends(get_services)) -> FileResponse:
    if services.avatars.get(avatar_id) is None:
        raise _not_found()
    path = services.avatars.path_for(avatar_id)
    if not path.is_file():
        raise AppError(404, "avatar_file_missing", "アバターのファイルが見つかりません。登録し直してください。")
    return FileResponse(path, media_type="model/gltf-binary", headers={"Cache-Control": "private, max-age=3600"})


@router.put("/{avatar_id}")
def update_avatar(body: AvatarUpdate, avatar_id: str = AvatarId, services: Services = Depends(get_services)) -> Avatar:
    avatar = services.avatars.update(avatar_id, body.name, body.is_placeholder)
    if avatar is None:
        raise _not_found()
    return avatar


@router.post("/{avatar_id}/activate")
def activate(avatar_id: str = AvatarId, services: Services = Depends(get_services)) -> dict:
    if services.avatars.get(avatar_id) is None:
        raise _not_found()
    services.settings.update({"avatar_id": avatar_id})
    return {"active_id": avatar_id}


@router.delete("/{avatar_id}")
def delete_avatar(avatar_id: str = AvatarId, services: Services = Depends(get_services)) -> dict:
    if not services.avatars.delete(avatar_id):
        raise _not_found()
    if services.settings.get().avatar_id == avatar_id:
        services.settings.update({"avatar_id": ""})
    return {"deleted": True}
