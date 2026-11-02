"""暗号化バックアップの作成と復元。"""

from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.backup import create_backup
from app.deps import Services, get_services
from app.errors import AppError
from app.schemas import BackupRequest, RestoreRequest
from app.services.data_protection import restore

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.post("")
async def backup(body: BackupRequest, services: Services = Depends(get_services)) -> Response:
    key = services.vault.cipher.key
    blob = await asyncio.to_thread(create_backup, services.db.path, key, body.passphrase)
    filename = f"twin-backup-{datetime.now():%Y%m%d-%H%M%S}.twinbak"
    return Response(
        content=blob,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.post("/restore")
async def restore_backup(body: RestoreRequest, services: Services = Depends(get_services)) -> dict:
    try:
        blob = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AppError(400, "invalid_backup", "バックアップファイルを読み取れませんでした。") from exc
    contents = await restore(services, blob, body.passphrase)
    return {"restored": True, "backup_created_at": contents.created_at}
