"""アバターの居場所（背景）・天気予報・自分で用意した背景画像。"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.backgrounds import Background
from app.services.scene import choose_scene, describe_for_ai
from tests.conftest import FakeOllama, FakeWeather

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def at(hour: int, day: int = 9) -> datetime:
    return datetime(2026, 11, day, hour, 0)


def test_stays_home_at_night_morning_and_in_bad_weather() -> None:
    assert choose_scene(at(23), None, "auto", []).kind == "room"
    assert choose_scene(at(7), None, "auto", []).status == "おうちで朝の準備中"
    rainy = choose_scene(at(13), "rain", "auto", [])
    assert rainy.kind == "room" and rainy.status == "雨だからおうちにいるよ"
    assert choose_scene(at(13), "snow", "auto", []).status == "雪だからおうちにいるよ"


def test_goes_out_in_the_daytime_and_keeps_the_place_within_a_slot() -> None:
    places = {choose_scene(at(h, d), "clear", "auto", []).kind for d in range(1, 15) for h in (10, 12, 14, 16, 18)}
    assert {"park", "street", "cafe"} <= places
    # 同じ2時間の中では同じ場所（開くたびに変わらない）
    assert choose_scene(at(10), "clear", "auto", []) == choose_scene(datetime(2026, 11, 9, 11, 30), "clear", "auto", [])


def test_period_follows_the_clock() -> None:
    assert choose_scene(at(6), None, "park", []).period == "dawn"
    assert choose_scene(at(12), None, "park", []).period == "day"
    assert choose_scene(at(17), None, "park", []).period == "evening"
    assert choose_scene(at(21), None, "park", []).period == "night"


def test_fixed_and_custom_scenes() -> None:
    home = Background(id="a" * 32, name="わたしの部屋", kind="home", ext="png", size=1)
    beach = Background(id="b" * 32, name="海", kind="outdoor", ext="png", size=1)
    assert choose_scene(at(13), None, "cafe", []).kind == "cafe"
    fixed = choose_scene(at(13), None, f"custom:{beach.id}", [home, beach])
    assert fixed.background_id == beach.id and not fixed.indoor and fixed.status == "海にいるよ"
    # 家の画像があれば、家にいるときはそれを使う
    assert choose_scene(at(23), None, "auto", [home, beach]).background_id == home.id
    # 消えた画像に固定されていたら、おでかけに戻る
    assert choose_scene(at(23), None, f"custom:{'c' * 32}", []).kind == "room"


def test_scene_api_without_weather(setup_done: TestClient, fake_weather: FakeWeather) -> None:
    body = setup_done.get("/api/scene").json()
    assert body["scene"]["weather"] is None and body["notice"] is None
    # 天気をオンにしていなければ、外には問い合わせない
    assert fake_weather.requests == []


def test_weather_place_and_forecast(setup_done: TestClient, fake_weather: FakeWeather) -> None:
    places = setup_done.get("/api/weather/places", params={"q": "神戸"}).json()["places"]
    assert places[0]["name"] == "神戸市"
    assert setup_done.post("/api/weather/place", json={"place": places[0]}).json()["place"] == "神戸市（兵庫県 日本）"
    setup_done.put("/api/settings", json={"weather_enabled": True})

    scene = setup_done.get("/api/scene").json()["scene"]
    # 雨なので、時間帯に関係なく家にいる
    assert scene["sky"] == "rain" and scene["kind"] == "room"
    assert scene["weather"]["label"] == "小雨" and scene["weather"]["today"]["rain_chance"] == 80
    # 送るのは緯度・経度だけ（名前や会話は送らない）
    forecast = [r for r in fake_weather.requests if "forecast" in r.url.path][0]
    assert set(forecast.url.params) == {"latitude", "longitude", "current", "daily", "timezone", "forecast_days"}
    # 30分はためておく
    setup_done.get("/api/scene")
    assert len([r for r in fake_weather.requests if "forecast" in r.url.path]) == 1


def test_weather_failure_still_returns_a_scene(setup_done: TestClient, fake_weather: FakeWeather) -> None:
    setup_done.put(
        "/api/settings",
        json={"weather_enabled": True, "weather_place": "神戸", "weather_latitude": 34.7, "weather_longitude": 135.2},
    )
    fake_weather.fail = True
    body = setup_done.get("/api/scene").json()
    assert body["scene"]["weather"] is None and "天気を取得できませんでした" in body["notice"]


def test_ai_knows_where_it_is_and_the_weather(setup_done: TestClient, fake_ollama: FakeOllama, fake_weather: FakeWeather) -> None:
    setup_done.put(
        "/api/settings",
        json={"weather_enabled": True, "weather_place": "神戸", "weather_latitude": 34.7, "weather_longitude": 135.2},
    )
    setup_done.post("/api/chat", json={"messages": [{"role": "user", "content": "今日の天気は？"}]})
    prompt = [b for b in fake_ollama.paths("/api/chat") if "format" not in b][-1]["messages"][0]["content"]
    assert "雨だからおうちにいるよ" in prompt and "神戸の天気" in prompt and "降水確率80%" in prompt
    assert "天気は「いまのようす」に書かれた内容だけを答える" in prompt


def test_describe_without_weather_does_not_claim_weather() -> None:
    text = describe_for_ai(choose_scene(at(13), None, "park", []))
    assert "公園をおさんぽ中" in text and "天気" not in text


def test_custom_backgrounds(setup_done: TestClient) -> None:
    created = setup_done.post("/api/backgrounds", params={"name": "海", "kind": "outdoor"}, content=PNG).json()
    assert created["kind"] == "outdoor" and created["ext"] == "png"
    file = setup_done.get(f"/api/backgrounds/{created['id']}/file")
    assert file.headers["content-type"] == "image/png" and file.content == PNG
    assert setup_done.put(f"/api/backgrounds/{created['id']}", json={"kind": "home"}).json()["kind"] == "home"

    setup_done.put("/api/settings", json={"scene_mode": f"custom:{created['id']}"})
    assert setup_done.get("/api/scene").json()["scene"]["background_id"] == created["id"]
    # 消したら、おでかけに戻る
    assert setup_done.delete(f"/api/backgrounds/{created['id']}").json() == {"deleted": True}
    assert setup_done.get("/api/settings").json()["scene_mode"] == "auto"
    assert setup_done.get("/api/backgrounds").json()["backgrounds"] == []


def test_rejects_non_images(setup_done: TestClient) -> None:
    res = setup_done.post("/api/backgrounds", content=b"<svg></svg>")
    assert res.status_code == 400 and "PNG" in res.json()["detail"]["message"]
