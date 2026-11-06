"""アバターの「いまいる場所」を決める。

アバターが生活しているように、時間帯と天気で居場所を変える。
- 夜・朝・雨や雪の日は家にいる。昼間は日ごと・2時間ごとに、公園・街・カフェなどへ出かける。
- 同じ時間帯の中では同じ場所にする（画面を開くたびに変わらないように）。
- 自分で用意した背景画像も、家・出かけ先として使う。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.backgrounds import Background
from app.services.weather import Sky, Weather

SceneKind = Literal["room", "park", "street", "cafe", "custom"]
Period = Literal["dawn", "day", "evening", "night"]

BUILTIN_SCENES: dict[str, tuple[str, bool]] = {
    # id: (場所の名前, 屋内か)
    "room": ("おうち", True),
    "park": ("公園", False),
    "street": ("街", False),
    "cafe": ("カフェ", True),
}

_ACTIVITY = {
    "park": "公園をおさんぽ中",
    "street": "街をぶらぶら中",
    "cafe": "カフェでひと休み中",
}


class Scene(BaseModel):
    kind: SceneKind
    # 自分で用意した背景のとき、その画像の id
    background_id: str | None = None
    place: str
    indoor: bool
    period: Period
    # 画面に出す「いまのようす」（例: 雨だからおうちにいるよ）
    status: str
    sky: Sky | None = None
    weather: Weather | None = None


def period_of(hour: int) -> Period:
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 16:
        return "day"
    if 16 <= hour < 19:
        return "evening"
    return "night"


def _pick(options: list, *keys: object) -> object:
    """日付と時間帯から決まる、毎回同じ選び方（乱数を使わない）。"""
    digest = hashlib.sha256("|".join(str(k) for k in keys).encode()).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def _home(now: datetime, customs: list[Background], status: str, period: Period, sky: Sky | None) -> Scene:
    homes = [b for b in customs if b.kind == "home"]
    if homes:
        bg = _pick(homes, now.date(), "home")
        assert isinstance(bg, Background)
        return Scene(kind="custom", background_id=bg.id, place=bg.name, indoor=True, period=period, status=status, sky=sky)
    return Scene(kind="room", place="おうち", indoor=True, period=period, status=status, sky=sky)


def _home_status(hour: int, sky: Sky | None) -> str:
    if sky == "rain":
        return "雨だからおうちにいるよ"
    if sky == "snow":
        return "雪だからおうちにいるよ"
    if sky == "thunder":
        return "雷が鳴ってるからおうちにいるよ"
    if 5 <= hour < 9:
        return "おうちで朝の準備中"
    if hour >= 22 or hour < 5:
        return "おうちでくつろぎ中"
    return "おうちでのんびり中"


def choose_scene(now: datetime, sky: Sky | None, mode: str, customs: list[Background]) -> Scene:
    """いまの場所を決める。mode: auto（おでかけする）/ room・park・street・cafe / custom:<id>（固定）"""
    period = period_of(now.hour)
    if mode.startswith("custom:"):
        bg = next((b for b in customs if b.id == mode.removeprefix("custom:")), None)
        if bg is not None:
            return Scene(
                kind="custom", background_id=bg.id, place=bg.name, indoor=bg.kind != "outdoor",
                period=period, status=f"{bg.name}にいるよ", sky=sky,
            )
        mode = "auto"
    if mode in BUILTIN_SCENES:
        place, indoor = BUILTIN_SCENES[mode]
        status = _home_status(now.hour, sky) if mode == "room" else _ACTIVITY[mode]
        return Scene(kind=mode, place=place, indoor=indoor, period=period, status=status, sky=sky)  # type: ignore[arg-type]

    hour = now.hour
    bad_weather = sky in ("rain", "snow", "thunder")
    # 夜・朝・夕食後と、雨や雪の日は家にいる
    if bad_weather or hour < 9 or hour >= 20:
        return _home(now, customs, _home_status(hour, sky), period, sky)
    # 昼間は2時間ごとに居場所が変わる。ときどき家でのんびりする
    spots: list[object] = ["park", "street", "cafe", "room"]
    spots += [b for b in customs if b.kind in ("indoor", "outdoor")]
    spot = _pick(spots, now.date(), hour // 2)
    if isinstance(spot, Background):
        return Scene(
            kind="custom", background_id=spot.id, place=spot.name, indoor=spot.kind == "indoor",
            period=period, status=f"{spot.name}にいるよ", sky=sky,
        )
    if spot == "room":
        return _home(now, customs, _home_status(hour, sky), period, sky)
    place, indoor = BUILTIN_SCENES[str(spot)]
    return Scene(kind=spot, place=place, indoor=indoor, period=period, status=_ACTIVITY[str(spot)], sky=sky)  # type: ignore[arg-type]


def describe_for_ai(scene: Scene) -> str:
    """AI に渡す「いまのようす」。聞かれたときに自然に話せるようにする。"""
    lines = [
        "## いまのあなたのようす（アプリが決めた設定。聞かれたら自然に話してよいが、毎回自分から持ち出さない）",
        f"- {scene.status}（場所: {scene.place}）。",
    ]
    w = scene.weather
    if w is not None:
        now = f"今は{w.label}" + (f"、{w.temperature:.0f}℃" if w.temperature is not None else "")
        today = f"今日は{w.today.label}"
        if w.today.temp_max is not None and w.today.temp_min is not None:
            today += f"（最高{w.today.temp_max:.0f}℃・最低{w.today.temp_min:.0f}℃"
            today += f"、降水確率{w.today.rain_chance}%）" if w.today.rain_chance is not None else "）"
        tomorrow = ""
        if w.tomorrow is not None:
            tomorrow = f"明日は{w.tomorrow.label}"
            if w.tomorrow.rain_chance is not None:
                tomorrow += f"（降水確率{w.tomorrow.rain_chance}%）"
            tomorrow += "。"
        lines.append(f"- {w.place}の天気（天気予報から取得した実際の情報）: {now}。{today}。{tomorrow}")
    return "\n".join(lines)
