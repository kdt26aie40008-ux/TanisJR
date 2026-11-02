"""Google カレンダー連携・予定操作（承認制）・通知設定。"""

from __future__ import annotations

from datetime import timedelta
from html import escape

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import HTMLResponse

from app.calendar.google import parse_client_json
from app.calendar.models import CalendarEvent, NotifyUpdate, Operation, OperationCreate, local_now
from app.deps import Services, get_services
from app.errors import AppError
from app.routers.speech import read_limited
from app.schemas import ID_PATTERN

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

OperationId = Path(pattern=ID_PATTERN)
EventId = Path(min_length=1, max_length=1024, pattern=r"^[A-Za-z0-9_\-]+$")


def redirect_uri(services: Services) -> str:
    return f"http://127.0.0.1:{services.config.port}/api/calendar/auth/callback"


@router.get("/status")
def status(services: Services = Depends(get_services)) -> dict:
    scheduler = services.scheduler
    return {
        **services.calendar.status(),
        "redirect_uri": redirect_uri(services),
        "last_sync_at": scheduler.last_sync_at if scheduler else None,
        "last_error": scheduler.last_error if scheduler else None,
    }


@router.post("/client")
async def upload_client(request: Request, services: Services = Depends(get_services)) -> dict:
    """Google Cloud で作成した「デスクトップアプリ」用 OAuth クライアントの JSON を登録する（暗号化して保存）。"""
    data = await read_limited(request, 64 * 1024)
    services.calendar.save_client(parse_client_json(data))
    return services.calendar.status()


@router.delete("/client")
async def remove_client(services: Services = Depends(get_services)) -> dict:
    await services.calendar.disconnect()
    services.settings.set_raw("google_client", None)
    return services.calendar.status()


@router.post("/auth/start")
def auth_start(services: Services = Depends(get_services)) -> dict:
    return {"url": services.calendar.start_auth(redirect_uri(services))}


def _page(title: str, message: str) -> HTMLResponse:
    body = (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>Google カレンダー連携</title>"
        "<style>body{font-family:'Segoe UI','Yu Gothic UI',sans-serif;background:#080d1a;color:#e6edf7;"
        "display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:32em;padding:2em;text-align:center}"
        "h1{color:#3ee0ff;font-size:1.3rem}</style></head>"
        f"<body><main><h1>{escape(title)}</h1><p>{escape(message)}</p></main></body></html>"
    )
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/auth/callback", include_in_schema=False)
async def auth_callback(
    state: str = Query(default="", max_length=200),
    code: str = Query(default="", max_length=2000),
    error: str = Query(default="", max_length=200),
    services: Services = Depends(get_services),
) -> HTMLResponse:
    """Google の同意画面からのリダイレクト先。state で正当な要求か確認する。"""
    if error:
        return _page("連携を中止しました", "Google での許可が行われませんでした。このタブを閉じてください。")
    try:
        await services.calendar.finish_auth(state, code)
    except Exception as exc:  # noqa: BLE001  画面に日本語で表示する
        message = getattr(exc, "message", "連携に失敗しました。もう一度お試しください。")
        return _page("連携に失敗しました", message)
    if services.scheduler:
        await services.scheduler.sync(force=True)
    return _page("Google カレンダーと連携しました", "このタブを閉じて、アプリの画面に戻ってください。")


@router.post("/disconnect")
async def disconnect(services: Services = Depends(get_services)) -> dict:
    await services.calendar.disconnect()
    return services.calendar.status()


@router.get("/events")
async def events(days: int = Query(default=14, ge=1, le=60), services: Services = Depends(get_services)) -> list[CalendarEvent]:
    now = local_now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return await services.calendar.list_events(start, start + timedelta(days=days))


@router.put("/events/{event_id}/notify")
def set_notify(body: NotifyUpdate, event_id: str = EventId, services: Services = Depends(get_services)) -> dict:
    services.calendar.set_notify(event_id, body.minutes)
    return {"event_id": event_id, "minutes": body.minutes}


# ---------- 操作の下書きと承認 ----------


@router.get("/operations")
def operations(
    status: str = Query(default="pending", pattern=r"^(pending|done|rejected|failed|all)$"),
    services: Services = Depends(get_services),
) -> list[Operation]:
    return services.calendar.list_operations(None if status == "all" else status)


@router.post("/operations")
async def create_operation(body: OperationCreate, services: Services = Depends(get_services)) -> Operation:
    """画面のフォームからの操作も、まず下書きとして保存する（実行は承認後）。"""
    return await services.calendar.propose(body, source="user")


@router.post("/operations/{op_id}/approve")
async def approve(op_id: str = OperationId, services: Services = Depends(get_services)) -> Operation:
    """ユーザーが画面の承認ボタンを押したときだけ呼ばれる。ここで初めて Google に反映する。"""
    op = await services.calendar.approve(op_id)
    if services.scheduler:
        await services.scheduler.sync(force=True)
    return op


@router.post("/operations/{op_id}/reject")
def reject(op_id: str = OperationId, services: Services = Depends(get_services)) -> Operation:
    return services.calendar.reject(op_id)


# ---------- 通知 ----------


@router.post("/notifications/test")
async def test_notification(services: Services = Depends(get_services)) -> dict:
    shown = await services.notifier.notify("通知のテスト", "第二の自分AIからの通知はこのように表示されます。")
    if not shown:
        raise AppError(500, "notify_failed", "通知を表示できませんでした。Windows の通知設定を確認してください。")
    return {"shown": True}
