"""スマホから使う（Tailscale 経由）の設定とペアリング。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from app.deps import Services, get_services
from app.errors import AppError
from app.remote import COOKIE_MAX_AGE, COOKIE_NAME, RemoteError
from app.schemas import ID_PATTERN, StrictModel
from app.security import is_remote

router = APIRouter(prefix="/api/remote", tags=["remote"])


def _error(exc: RemoteError) -> AppError:
    return AppError(exc.status, exc.code, exc.message)


def _status(services: Services) -> dict:
    s = services.settings.get()
    tailscale = services.remote.tailscale_status()
    host = services.remote.host
    return {
        "enabled": s.remote_enabled,
        "tailscale": tailscale,
        "url": f"https://{host}" if s.remote_enabled and host else None,
        "devices": services.remote.devices(),
    }


@router.get("/status")
def status(services: Services = Depends(get_services)) -> dict:
    return _status(services)


@router.post("/enable")
def enable(services: Services = Depends(get_services)) -> dict:
    try:
        host = services.remote.enable()
    except RemoteError as exc:
        raise _error(exc) from exc
    services.settings.update({"remote_enabled": True, "remote_host": host})
    return _status(services)


@router.post("/disable")
def disable(services: Services = Depends(get_services)) -> dict:
    services.remote.disable()
    services.settings.update({"remote_enabled": False})
    return _status(services)


@router.post("/pairing")
def start_pairing(services: Services = Depends(get_services)) -> dict:
    if not services.settings.get().remote_enabled or not services.remote.host:
        raise AppError(409, "remote_disabled", "先に「スマホから使う」をオンにしてください。")
    pin, expires = services.remote.start_pairing()
    return {"pin": pin, "expires_at": expires, "url": f"https://{services.remote.host}"}


@router.delete("/devices/{device_id}")
def remove_device(device_id: str = Path(pattern=ID_PATTERN), services: Services = Depends(get_services)) -> dict:
    if not services.remote.remove(device_id):
        raise AppError(404, "device_not_found", "端末が見つかりません。")
    return {"deleted": True}


class PairRequest(StrictModel):
    pin: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    name: str = Field(default="", max_length=40)


@router.post("/pair")
def pair(body: PairRequest, request: Request, services: Services = Depends(get_services)) -> JSONResponse:
    """スマホから合言葉を送って、この端末を登録する（Tailscale 経由のときだけ）。"""
    if not is_remote(request, services.remote):
        raise AppError(400, "not_remote", "ペアリングはスマホから行ってください。")
    try:
        token = services.remote.pair(body.pin, body.name)
    except RemoteError as exc:
        raise _error(exc) from exc
    response = JSONResponse({"paired": True})
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True, secure=True, samesite="strict", path="/"
    )
    return response


@router.get("/me")
def me(request: Request, services: Services = Depends(get_services)) -> dict:
    remote = is_remote(request, services.remote)
    return {"remote": remote, "paired": (not remote) or services.remote.check(request.cookies.get(COOKIE_NAME))}
