"""声を増やす（AivisHub から追加）・声を作る（高さ・速さなどの調整）。"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tests.conftest import HUB_ELDER, HUB_SAMPLE, SPEAKER_UUID, FakeAivis, FakeVoiceHub
from tests.test_remote import enable, phone

STYLE = 888753760
VOICE = {"id": "0a1b2c3d", "name": "おじいちゃん風", "style_id": STYLE, "speed": 0.85, "pitch": -0.06,
         "intonation": 0.8, "tempo": 0.7, "volume": 1.0}


def _ready(client: TestClient) -> None:
    client.put("/api/settings", json={"tts_speaker": STYLE})
    client.post("/api/speech/tts/acknowledge", json={"speaker_uuid": SPEAKER_UUID})


def _synthesis_query(fake_aivis: FakeAivis) -> dict:
    return [r for r in fake_aivis.requests if r["path"] == "/synthesis"][-1]["json"]


# ---------- 声を作る ----------


def test_custom_voice_is_used_for_reading(client: TestClient, fake_aivis: FakeAivis) -> None:
    _ready(client)
    res = client.put("/api/settings", json={"tts_custom_voices": [VOICE], "tts_voice": VOICE["id"]})
    assert res.status_code == 200, res.text
    assert client.post("/api/speech/tts", json={"text": "こんにちは"}).status_code == 200
    query = _synthesis_query(fake_aivis)
    assert query["speedScale"] == 0.85
    assert query["pitchScale"] == -0.06
    assert query["intonationScale"] == 0.8
    assert query["tempoDynamicsScale"] == 0.7


def test_original_voice_uses_default_tune(client: TestClient, fake_aivis: FakeAivis) -> None:
    _ready(client)
    client.put("/api/settings", json={"tts_speed": 1.2})
    client.post("/api/speech/tts", json={"text": "こんにちは"})
    query = _synthesis_query(fake_aivis)
    assert query["speedScale"] == 1.2 and query["pitchScale"] == 0.0 and query["intonationScale"] == 1.0


def test_preview_unsaved_tune(client: TestClient, fake_aivis: FakeAivis) -> None:
    _ready(client)
    tune = {k: VOICE[k] for k in ("style_id", "speed", "pitch", "intonation", "tempo", "volume")} | {"pitch": 0.12}
    assert client.post("/api/speech/tts", json={"text": "やあ", "tune": tune}).status_code == 200
    assert _synthesis_query(fake_aivis)["pitchScale"] == 0.12


def test_custom_voice_validation(client: TestClient) -> None:
    # 高さは AivisSpeech の範囲（-0.15〜0.15）まで
    assert client.put("/api/settings", json={"tts_custom_voices": [VOICE | {"pitch": 0.3}]}).status_code == 422
    assert client.put("/api/settings", json={"tts_custom_voices": [VOICE | {"name": "  "}]}).status_code == 422
    assert client.put("/api/settings", json={"tts_custom_voices": [VOICE, VOICE]}).status_code == 400
    # 作っていない声は選べない（元の声のまま）
    client.put("/api/settings", json={"tts_voice": "ffffffff"})
    assert client.get("/api/settings").json()["tts_voice"] is None


def test_deleting_the_voice_in_use_returns_to_the_original(client: TestClient) -> None:
    client.put("/api/settings", json={"tts_custom_voices": [VOICE], "tts_voice": VOICE["id"]})
    assert client.get("/api/settings").json()["tts_voice"] == VOICE["id"]
    client.put("/api/settings", json={"tts_custom_voices": []})
    assert client.get("/api/settings").json()["tts_voice"] is None
    # "" で元の声に戻す
    client.put("/api/settings", json={"tts_custom_voices": [VOICE], "tts_voice": VOICE["id"]})
    client.put("/api/settings", json={"tts_voice": ""})
    settings = client.get("/api/settings").json()
    assert settings["tts_voice"] is None and len(settings["tts_custom_voices"]) == 1


# ---------- 声を増やす ----------


def test_hub_list_by_timbre(client: TestClient, fake_hub: FakeVoiceHub) -> None:
    data = client.get("/api/speech/voices/hub", params={"timbre": ["ElderlyMale", "MiddleAgedMale"]}).json()
    assert fake_hub.searches[-1] == ["ElderlyMale", "MiddleAgedMale"]
    voice = data["voices"][0]
    assert voice["name"] == "おじいちゃんの声" and voice["timbre_label"] == "おじいちゃん"
    assert voice["file_size"] == 252925401 and voice["license_type"] == "ACML 1.0"
    assert voice["installed"] is False
    assert {"id": "YoungMale", "label": "男の子"} in data["timbres"]
    assert client.get("/api/speech/voices/hub", params={"timbre": "Robot"}).status_code == 422


def test_hub_sample_only_from_aivishub(client: TestClient, fake_hub: FakeVoiceHub) -> None:
    # 一覧に出る前は試聴できない
    assert client.get(f"/api/speech/voices/hub/{HUB_ELDER}/sample/0").status_code == 404
    client.get("/api/speech/voices/hub")
    assert client.get(f"/api/speech/voices/hub/{HUB_ELDER}/sample/0").status_code == 200
    # AivisHub 以外の場所の音声は取り寄せない
    assert client.get(f"/api/speech/voices/hub/{HUB_ELDER}/sample/1").status_code == 404
    assert fake_hub.sample_requests == [HUB_SAMPLE]


def test_install_voice(client: TestClient, fake_aivis: FakeAivis) -> None:
    client.get("/api/speech/voices/hub")
    body = {"aivm_uuid": HUB_ELDER, "confirmed": False}
    assert client.post("/api/speech/voices/install", json=body).json()["detail"]["code"] == "confirmation_required"
    res = client.post("/api/speech/voices/install", json=body | {"confirmed": True})
    assert res.status_code == 202, res.text
    for _ in range(50):
        job = client.get("/api/speech/voices/installed").json()["job"]
        if job["state"] != "installing":
            break
        time.sleep(0.02)
    assert job == {"state": "done", "aivm_uuid": HUB_ELDER, "name": "おじいちゃんの声", "error": ""}
    assert fake_aivis.installed_urls == [
        f"https://api.aivis-project.com/v1/aivm-models/{HUB_ELDER}/download?model_type=AIVMX"
    ]
    assert client.get("/api/speech/voices/hub").json()["voices"][0]["installed"] is True


def test_install_unknown_voice_is_rejected(client: TestClient) -> None:
    other = "11111111-2222-3333-4444-555555555555"
    res = client.post("/api/speech/voices/install", json={"aivm_uuid": other, "confirmed": True})
    assert res.json()["detail"]["code"] == "voice_not_found"


def test_uninstall_voice(client: TestClient, fake_aivis: FakeAivis) -> None:
    only = next(iter(fake_aivis.models))
    # 最後の1つは消せない
    assert client.delete(f"/api/speech/voices/{only}").json()["detail"]["code"] == "last_voice"
    fake_aivis.models[HUB_ELDER] = "おじいちゃんの声"
    assert client.delete(f"/api/speech/voices/{HUB_ELDER}").status_code == 200
    assert HUB_ELDER not in fake_aivis.models
    assert client.delete(f"/api/speech/voices/{HUB_ELDER}").json()["detail"]["code"] == "voice_not_found"


def test_phone_cannot_add_voices(setup_done: TestClient) -> None:
    enable(setup_done)
    pin = setup_done.post("/api/remote/pairing").json()["pin"]
    p = phone(setup_done)
    p.post("/api/remote/pair", json={"pin": pin})
    res = p.post("/api/speech/voices/install", json={"aivm_uuid": HUB_ELDER, "confirmed": True})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "local_only"
