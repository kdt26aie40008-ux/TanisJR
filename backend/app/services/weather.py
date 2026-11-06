"""天気予報（Open-Meteo）。

- 設定でオンにしたときだけ使う（既定はオフ）。送るのは設定した場所の緯度・経度だけで、会話や名前は送らない。
- 無料・登録不要（https://open-meteo.com/ 。商用でない利用は無料、データは CC BY 4.0）。
- 結果は30分ためておき、何度も問い合わせない。
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
CACHE_SECONDS = 30 * 60

Sky = Literal["clear", "cloudy", "fog", "rain", "snow", "thunder"]


class WeatherError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def sky_of(code: int) -> Sky:
    """WMO の天気コードを、背景の描き分けに使う6種類にまとめる。"""
    if code in (0, 1):
        return "clear"
    if code in (2, 3):
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code >= 95:
        return "thunder"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    return "cloudy"


_LABELS = {
    0: "快晴", 1: "晴れ", 2: "晴れ時々くもり", 3: "くもり", 45: "霧", 48: "霧",
    51: "霧雨", 53: "霧雨", 55: "霧雨", 56: "着氷性の霧雨", 57: "着氷性の霧雨",
    61: "小雨", 63: "雨", 65: "大雨", 66: "着氷性の雨", 67: "着氷性の雨",
    71: "小雪", 73: "雪", 75: "大雪", 77: "雪",
    80: "にわか雨", 81: "にわか雨", 82: "激しいにわか雨", 85: "にわか雪", 86: "激しいにわか雪",
    95: "雷雨", 96: "ひょうを伴う雷雨", 99: "ひょうを伴う雷雨",
}


def label_of(code: int) -> str:
    return _LABELS.get(code, "くもり")


class DayForecast(BaseModel):
    code: int
    label: str
    sky: Sky
    temp_max: float | None = None
    temp_min: float | None = None
    rain_chance: int | None = None


class Weather(BaseModel):
    place: str
    code: int
    label: str
    sky: Sky
    temperature: float | None
    is_day: bool
    today: DayForecast
    tomorrow: DayForecast | None = None
    fetched_at: float


class Place(BaseModel):
    name: str
    detail: str
    latitude: float
    longitude: float


class WeatherService:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(timeout=10, transport=transport, headers={"User-Agent": "AnotherMe"})
        self._cache: dict[tuple[float, float], Weather] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, name: str) -> list[Place]:
        """地名から候補を探す（設定画面で場所を選ぶため）。"""
        try:
            res = await self._client.get(GEOCODING_URL, params={"name": name, "count": 6, "language": "ja", "format": "json"})
            res.raise_for_status()
            items = res.json().get("results") or []
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Geocoding failed: %s", type(exc).__name__)
            raise WeatherError("場所を探せませんでした。インターネットにつながっているか確認してください。") from exc
        places = []
        for item in items:
            detail = " ".join(str(p) for p in (item.get("admin1"), item.get("country")) if p)
            places.append(
                Place(name=str(item.get("name", "")), detail=detail, latitude=float(item["latitude"]), longitude=float(item["longitude"]))
            )
        return places

    async def current(self, place: str, latitude: float, longitude: float) -> Weather:
        key = (round(latitude, 3), round(longitude, 3))
        cached = self._cache.get(key)
        if cached and time.time() - cached.fetched_at < CACHE_SECONDS:
            return cached.model_copy(update={"place": place})
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 2,
        }
        try:
            res = await self._client.get(FORECAST_URL, params=params)
            res.raise_for_status()
            data = res.json()
            current = data["current"]
            daily = data["daily"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("Weather fetch failed: %s", type(exc).__name__)
            raise WeatherError("天気を取得できませんでした。インターネットにつながっているか確認してください。") from exc

        def day(i: int) -> DayForecast | None:
            codes = daily.get("weather_code") or []
            if i >= len(codes) or codes[i] is None:
                return None
            pick = lambda name: (daily.get(name) or [None] * (i + 1))[i]  # noqa: E731
            code = int(codes[i])
            chance = pick("precipitation_probability_max")
            return DayForecast(
                code=code, label=label_of(code), sky=sky_of(code),
                temp_max=pick("temperature_2m_max"), temp_min=pick("temperature_2m_min"),
                rain_chance=int(chance) if chance is not None else None,
            )

        code = int(current.get("weather_code", 3))
        today = day(0) or DayForecast(code=code, label=label_of(code), sky=sky_of(code))
        weather = Weather(
            place=place, code=code, label=label_of(code), sky=sky_of(code),
            temperature=current.get("temperature_2m"), is_day=bool(current.get("is_day", 1)),
            today=today, tomorrow=day(1), fetched_at=time.time(),
        )
        self._cache[key] = weather
        return weather
