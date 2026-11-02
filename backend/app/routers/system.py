"""バックグラウンドサービスの状態・自動起動・停止・再起動。"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict

from app import system
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


@router.post("/stop", status_code=202)
def stop(background: BackgroundTasks, services: Services = Depends(get_services)) -> dict:
    if not services.allow_process_control:
        raise AppError(409, "not_allowed", "この環境では停止できません。")
    background.add_task(_exit_soon)
    return {"stopping": True}
