"""バックグラウンドサービスの状態・自動起動・停止・再起動。"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict

from app import system
from app.data_location import request_start_fresh
from app.deps import Services, get_services
from app.errors import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

STARTED_AT = time.time()


class AutostartUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


@router.get("/status")
def status(services: Services = Depends(get_services)) -> dict:
    return {
        "pid": os.getpid(),
        "uptime_seconds": int(time.time() - STARTED_AT),
        # --background（pythonw）で動いていればコンソールのないバックグラウンド実行
        "background": services.background,
        "autostart": system.autostart_enabled(services.startup_dir),
        "notifications_enabled": services.settings.get().notifications_enabled,
        "data_dir": str(services.config.data_dir),
    }


@router.put("/autostart")
def set_autostart(body: AutostartUpdate, services: Services = Depends(get_services)) -> dict:
    try:
        if body.enabled:
            system.enable_autostart(services.startup_dir)
        else:
            system.disable_autostart(services.startup_dir)
    except system.AutostartError as exc:
        raise AppError(500, "autostart_failed", exc.message) from exc
    return {"autostart": system.autostart_enabled(services.startup_dir)}


async def _exit_soon() -> None:
    # 応答を返し終えてから終了する
    await asyncio.sleep(0.5)
    logger.info("Server is stopping by user request")
    os._exit(0)


@router.post("/restart", status_code=202)
def restart(background: BackgroundTasks, services: Services = Depends(get_services)) -> dict:
    if not services.allow_process_control:
        raise AppError(409, "not_allowed", "この環境では再起動できません。")
    # 新しいプロセスは、このプロセスがポートを解放するのを待ってから起動する
    system.spawn_background_server()
    background.add_task(_exit_soon)
    return {"restarting": True}


class StartFreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 今のデータは退避され、使えなくなることを確認した
    confirmed: bool


@router.post("/start-fresh", status_code=202)
def start_fresh(body: StartFreshRequest, background: BackgroundTasks, services: Services = Depends(get_services)) -> dict:
    """読めなくなったデータ（別のPC・別のユーザーのデータなど）を退避して、空の状態から始め直す。

    データがロックされているときだけ使える。データは削除せず、別名フォルダーに残す。
    """
    if not services.vault.locked:
        raise AppError(409, "not_locked", "データは正常に読み込めています。新しく始める必要はありません。")
    if not body.confirmed:
        raise AppError(400, "confirmation_required", "今のデータが使えなくなることを確認してください。")
    request_start_fresh(services.config.data_dir)
    if not services.allow_process_control:
        return {"restarting": False}
    # 開いているファイルは移動できないため、再起動して起動時に退避する
    system.spawn_background_server()
    background.add_task(_exit_soon)
    return {"restarting": True}


@router.post("/stop", status_code=202)
def stop(background: BackgroundTasks, services: Services = Depends(get_services)) -> dict:
    if not services.allow_process_control:
        raise AppError(409, "not_allowed", "この環境では停止できません。")
    background.add_task(_exit_soon)
    return {"stopping": True}
