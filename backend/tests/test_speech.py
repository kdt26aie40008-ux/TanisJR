from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.speech.stt import SttError, WhisperService, decode_audio
from app.speech.tts import clean_for_speech
from tests.conftest import SPEAKER_UUID, WAV_BYTES, FakeAivis, FakeTranscriber

STYLE = 888753760


def make_wav(seconds: float = 0.5, rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(seconds * rate))
        )
        w.writeframes(frames)
    return buf.getvalue()


# ---------- 音声認識 ----------


def test_stt_returns_text_and_does_not_store_audio(client: TestClient, fake_stt: FakeTranscriber, config) -> None:  # noqa: ANN001
    before = {p for p in config.data_dir.rglob("*")}
    response = client.post("/api/speech/stt", content=b"fake-audio-bytes", headers={"Content-Type": "audio/webm"})
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "こんにちは"
    assert fake_stt.calls == [(16, "large-v3-turbo", "cpu")]
    # 音声ファイルは作られない
    assert {p for p in config.data_dir.rglob("*") if not p.name.startswith("twin.db")} <= before | {
        p for p in config.data_dir.rglob("*") if p.name.startswith("twin.db")
    }


def test_stt_uses_settings(client: TestClient, fake_stt: FakeTranscriber) -> None:
    client.put("/api/settings", json={"stt_model": "small", "stt_device": "cuda"})
    client.post("/api/speech/stt", content=b"x")
    assert fake_stt.calls[-1][1:] == ("small", "cuda")


def test_stt_empty_and_too_large(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    assert client.post("/api/speech/stt", content=b"").json()["detail"]["code"] == "empty_audio"
    monkeypatch.setattr("app.routers.speech.MAX_AUDIO_BYTES", 10)
    assert client.post("/api/speech/stt", content=b"x" * 11).status_code == 413


def test_stt_errors_are_japanese(client: TestClient, fake_stt: FakeTranscriber) -> None:
    fake_stt.error = SttError("音声認識モデル「x」がダウンロードされていません。", "stt_model_missing", 409)
    response = client.post("/api/speech/stt", content=b"x")
    assert response.status_code == 409
    assert "ダウンロード" in response.json()["detail"]["message"]


def test_whisper_download_requires_confirmation(client: TestClient, fake_stt: FakeTranscriber) -> None:
    assert client.post("/api/speech/stt/models/download", json={"model": "small", "confirmed": False}).status_code == 400
    assert client.post("/api/speech/stt/models/download", json={"model": "evil/model", "confirmed": True}).status_code == 422
    assert client.post("/api/speech/stt/models/download", json={"model": "small", "confirmed": True}).status_code == 202
    assert fake_stt.downloads == ["small"]


def test_stt_warmup_runs_in_background(client: TestClient, fake_stt: FakeTranscriber) -> None:
    assert client.post("/api/speech/stt/warmup").status_code == 202
    assert fake_stt.warmed == ("large-v3-turbo", "cpu")


def test_stt_settings_validation(client: TestClient) -> None:
    assert client.put("/api/settings", json={"stt_model": "huge"}).status_code == 422
    assert client.put("/api/settings", json={"stt_device": "tpu"}).status_code == 422


def test_decode_audio_wav() -> None:
    samples = decode_audio(make_wav(0.5))
    assert abs(len(samples) - 8000) < 200  # 16kHz に変換される
    assert samples.dtype.name == "float32"


def test_decode_audio_rejects_garbage() -> None:
    with pytest.raises(SttError, match="読み取れません"):
        decode_audio(b"not audio at all" * 10)


def test_whisper_service_reports_missing_model(tmp_path: Path) -> None:
    service = WhisperService(tmp_path / "whisper")
    status = service.status()
    assert all(not m["installed"] for m in status["models"])
    with pytest.raises(SttError) as exc:
        service._transcribe_sync(make_wav(0.3), "base", "cpu")
    assert exc.value.code == "stt_model_missing"


# ---------- 音声合成 ----------


def test_clean_for_speech() -> None:
    text = "**大事**です。詳しくは https://example.com を見て。\n```python\nprint(1)\n```\n# 見出し"
    cleaned = clean_for_speech(text)
    assert "**" not in cleaned and "https" not in cleaned and "print" not in cleaned and "#" not in cleaned
    assert "大事です。" in cleaned


def test_speakers_list(client: TestClient) -> None:
    data = client.get("/api/speech/tts/speakers").json()
    assert data["available"] is True
    assert data["speakers"][0]["styles"][0]["id"] == STYLE
    assert data["speakers"][0]["acknowledged"] is False


def test_speakers_when_engine_down(client: TestClient, fake_aivis: FakeAivis) -> None:
    fake_aivis.available = False
    data = client.get("/api/speech/tts/speakers").json()
    assert data["available"] is False
    assert "AivisSpeech" in data["message"]


def test_engine_autostart_when_down(client: TestClient, fake_aivis: FakeAivis, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """AivisSpeech のアプリが起動していなくても、エンジンだけを起動する。"""
    engine = client.app.state.services.tts_engine
    exe = tmp_path / "aivis" / "run.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    engine.engine_path = exe
    spawned: list[bool] = []

    def fake_spawn() -> None:
        spawned.append(True)
        fake_aivis.available = True  # 起動したらエンジンが応答する

    monkeypatch.setattr(engine, "_spawn", fake_spawn)
    fake_aivis.available = False
    data = client.get("/api/speech/tts/speakers").json()
    assert data["available"] is False and "起動しています" in data["message"]
    assert data["engine"]["installed"] is True
    # バックグラウンドの起動が終わると、話者を取得できる
    for _ in range(40):
        if client.get("/api/speech/tts/speakers").json()["available"]:
            break
        import time

        time.sleep(0.1)
    assert spawned == [True]
    assert client.get("/api/speech/tts/speakers").json()["available"] is True


def test_engine_not_started_when_disabled(client: TestClient, fake_aivis: FakeAivis, tmp_path) -> None:  # noqa: ANN001
    client.put("/api/settings", json={"tts_engine_autostart": False})
    fake_aivis.available = False
    data = client.get("/api/speech/tts/speakers").json()
    assert "起動しています" not in data["message"]
    assert client.app.state.services.tts_engine.starting is False


def test_policy_excludes_images(client: TestClient) -> None:
    data = client.get(f"/api/speech/tts/speakers/{SPEAKER_UUID}/policy").json()
    assert "クレジット" in data["policy"]
    assert "BASE64" not in str(data)


def test_tts_requires_speaker_and_license_ack(client: TestClient) -> None:
    response = client.post("/api/speech/tts", json={"text": "こんにちは"})
    assert response.json()["detail"]["code"] == "tts_speaker_not_selected"
    client.put("/api/settings", json={"tts_speaker": STYLE})
    response = client.post("/api/speech/tts", json={"text": "こんにちは"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "tts_license_not_acknowledged"

    assert client.post("/api/speech/tts/acknowledge", json={"speaker_uuid": SPEAKER_UUID}).status_code == 200
    response = client.post("/api/speech/tts", json={"text": "こんにちは"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == WAV_BYTES


def test_tts_applies_speed_and_cleans_text(client: TestClient, fake_aivis: FakeAivis) -> None:
    client.put("/api/settings", json={"tts_speaker": STYLE, "tts_speed": 1.3})
    client.post("/api/speech/tts/acknowledge", json={"speaker_uuid": SPEAKER_UUID})
    client.post("/api/speech/tts", json={"text": "**強調**して"})
    query = next(r for r in fake_aivis.requests if r["path"] == "/audio_query")
    assert query["params"]["text"] == "強調して"


def test_tts_unknown_speaker_and_engine_down(client: TestClient, fake_aivis: FakeAivis) -> None:
    assert client.post("/api/speech/tts", json={"text": "x", "speaker": 1}).status_code == 404
    assert client.post("/api/speech/tts/acknowledge", json={"speaker_uuid": "0000-1111"}).status_code == 404
    client.post("/api/speech/tts/acknowledge", json={"speaker_uuid": SPEAKER_UUID})
    client.app.state.services.tts._speakers = None  # 話者一覧のキャッシュを捨てて、エンジン停止を再現する
    fake_aivis.available = False
    response = client.post("/api/speech/tts", json={"text": "x", "speaker": STYLE})
    assert response.status_code == 503
    assert "起動" in response.json()["detail"]["message"]
