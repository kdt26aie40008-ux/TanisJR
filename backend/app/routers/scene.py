"""アバターの居場所（背景）・天気予報・自分で用意した背景画像。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import FileResponse

from app.backgrounds import MAX_BACKGROUND_BYTES, Background, BackgroundError, BackgroundKind
from app.deps import Services, get_services
from app.errors import AppError
from app.routers.speech import read_limited
from app.schemas import ID_PATTERN, StrictModel
from app.services.scene import Scene, choose_scene
from app.services.weather import Place, Weather, WeatherError

router = APIRouter(prefix="/api", tags=["scene"])

BackgroundId = Path(pattern=ID_PATTERN)


async def current_weather(services: Services) -> tuple[Weather | None, str | None]:
    """天気を使う設定なら取得する。失敗しても背景は出す（天気なしで決める）。"""
    s = services.settings.get()
    if not s.weather_enabled or s.weather_latitude is None or s.weather_longitude is None:
        return None, None
    try:
        return await services.weather.current(s.weather_place, s.weather_latitude, s.weather_longitude), None
    except WeatherError as exc:
        return None, exc.message


async def current_scene(services: Services) -> tuple[Scene, str | None]:
    weather, notice = await current_weather(services)
    scene = choose_scene(datetime.now(), weather.sky if weather else None, services.settings.get().scene_mode, services.backgrounds.list())
    return scene.model_copy(update={"weather": weather}), notice


@router.get("/scene")
async def get_scene(services: Services = Depends(get_services)) -> dict:
    scene, notice = await current_scene(services)
    return {"scene": scene, "notice": notice}


@router.get("/weather/places")
async def search_places(q: str = Query(min_length=1, max_length=64), services: Services = Depends(get_services)) -> dict:
    """設定画面で場所を選ぶための候補。地名だけを Open-Meteo に送る。"""
    try:
        return {"places": [p.model_dump() for p in await services.weather.search(q)]}
    except WeatherError as exc:
        raise AppError(502, "weather_unavailable", exc.message) from exc


class PlaceChoice(StrictModel):
    place: Place


@router.post("/weather/place")
def choose_place(body: PlaceChoice, services: Services = Depends(get_services)) -> dict:
    p = body.place
    label = f"{p.name}（{p.detail}）" if p.detail else p.name
    services.settings.update(
        {"weather_place": label[:64], "weather_latitude": round(p.latitude, 3), "weather_longitude": round(p.longitude, 3)}
    )
    return {"place": label[:64]}


# ---------- 自分で用意した背景画像 ----------


@router.get("/backgrounds")
def list_backgrounds(services: Services = Depends(get_services)) -> dict:
    return {"backgrounds": services.backgrounds.list()}


@router.post("/backgrounds")
async def upload_background(
    request: Request,
    name: str = Query(default="", max_length=40),
    kind: BackgroundKind = "indoor",
    services: Services = Depends(get_services),
) -> Background:
    data = await read_limited(request, MAX_BACKGROUND_BYTES)
    try:
        return services.backgrounds.add(data, name, kind)
    except BackgroundError as exc:
        raise AppError(exc.status, "invalid_background", exc.message) from exc


class BackgroundUpdate(StrictModel):
    name: str | None = None
    kind: BackgroundKind | None = None


@router.put("/backgrounds/{background_id}")
def update_background(
    body: BackgroundUpdate, background_id: str = BackgroundId, services: Services = Depends(get_services)
) -> Background:
    bg = services.backgrounds.update(background_id, body.name, body.kind)
    if bg is None:
        raise AppError(404, "background_not_found", "背景が見つかりません。")
    return bg


@router.delete("/backgrounds/{background_id}")
def delete_background(background_id: str = BackgroundId, services: Services = Depends(get_services)) -> dict:
    if not services.backgrounds.delete(background_id):
        raise AppError(404, "background_not_found", "背景が見つかりません。")
    if services.settings.get().scene_mode == f"custom:{background_id}":
        services.settings.update({"scene_mode": "auto"})
    return {"deleted": True}


@router.get("/backgrounds/{background_id}/file")
def background_file(background_id: str = BackgroundId, services: Services = Depends(get_services)) -> FileResponse:
    bg = services.backgrounds.get(background_id)
    if bg is None:
        raise AppError(404, "background_not_found", "背景が見つかりません。")
    return FileResponse(
        services.backgrounds.path_for(bg), media_type=services.backgrounds.media_type(bg),
        headers={"Cache-Control": "private, max-age=3600"},
    )
