"""AivisSpeech Engine（VOICEVOX 互換 API）による音声合成。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

MAX_TTS_CHARS = 300
_SPEAKER_CACHE_SECONDS = 30


class TtsError(Exception):
    """ユーザーに表示できる日本語メッセージを持つ例外。"""

    def __init__(self, message: str, code: str = "tts_error", status: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def unavailable() -> TtsError:
    return TtsError(
        "AivisSpeech に接続できません。AivisSpeech を起動してください。", "tts_unavailable", 503
    )


_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_URL = re.compile(r"https?://\S+")
_MARKDOWN = re.compile(r"[*_#`>|~\[\]]")
_SPACES = re.compile(r"\s+")


def clean_for_speech(text: str) -> str:
    """読み上げに不要な記号・URL・コードを取り除く。"""
    text = _CODE_BLOCK.sub("（コードは省略します）", text)
    text = _URL.sub("（URL）", text)
    text = _MARKDOWN.sub("", text)
    return _SPACES.sub(" ", text).strip()[:MAX_TTS_CHARS]


@dataclass(frozen=True)
class VoiceTune:
    """声の調整（AivisSpeech の AudioQuery の値）。

    pitch は -0.15〜0.15（0 以外にすると AivisSpeech の仕様で少し音質が落ちる）。
    intonation はスタイルらしさの強さ、tempo は話す速さの緩急。
    """

    speed: float = 1.0
    pitch: float = 0.0
    intonation: float = 1.0
    tempo: float = 1.0
    volume: float = 1.0


class AivisClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(connect=3.0, read=60.0, write=10.0, pool=3.0), transport=transport
        )
        self._speakers: list[dict[str, Any]] | None = None
        self._speakers_at = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise unavailable() from exc
        if response.status_code != 200:
            raise TtsError("音声の合成に失敗しました。話者の設定を確認してください。", "tts_failed", 502)
        return response

    async def version(self) -> str:
        return (await self._request("GET", "/version")).json()

    async def speakers(self) -> list[dict[str, Any]]:
        if self._speakers is None or time.monotonic() - self._speakers_at > _SPEAKER_CACHE_SECONDS:
            data = (await self._request("GET", "/speakers")).json()
            self._speakers = [
                {
                    "name": str(s.get("name", "")),
                    "speaker_uuid": str(s.get("speaker_uuid", "")),
                    "styles": [{"id": int(st["id"]), "name": str(st.get("name", ""))} for st in s.get("styles", [])],
                }
                for s in data
            ]
            self._speakers_at = time.monotonic()
        return self._speakers

    async def speaker_uuid_for_style(self, style_id: int) -> str | None:
        for speaker in await self.speakers():
            if any(st["id"] == style_id for st in speaker["styles"]):
                return speaker["speaker_uuid"]
        return None

    async def policy(self, speaker_uuid: str) -> str:
        data = (await self._request("GET", "/speaker_info", params={"speaker_uuid": speaker_uuid})).json()
        # 画像（base64）は不要なので利用規約の本文だけ返す
        return str(data.get("policy", ""))

    async def synthesize(self, text: str, style_id: int, tune: VoiceTune | float = 1.0) -> bytes:
        if not isinstance(tune, VoiceTune):
            tune = VoiceTune(speed=tune)
        query = (await self._request("POST", "/audio_query", params={"text": text, "speaker": style_id})).json()
        query["speedScale"] = tune.speed
        query["pitchScale"] = tune.pitch
        query["intonationScale"] = tune.intonation
        query["tempoDynamicsScale"] = tune.tempo
        query["volumeScale"] = tune.volume
        response = await self._request("POST", "/synthesis", params={"speaker": style_id}, json=query)
        return response.content

    # ---------- 声のモデル（AIVMX）の管理 ----------

    async def installed_models(self) -> list[dict[str, Any]]:
        """インストール済みの音声モデル（aivm_uuid・名前・含まれる話者の speaker_uuid）。"""
        data = (await self._request("GET", "/aivm_models")).json()
        return [
            {
                "aivm_uuid": str(uuid),
                "name": str((info.get("manifest") or {}).get("name") or uuid),
                "speaker_uuids": [
                    str((s.get("speaker") or {}).get("speaker_uuid", "")) for s in info.get("speakers") or []
                ],
            }
            for uuid, info in data.items()
        ]

    async def install_model(self, url: str) -> None:
        """URL の音声モデルを AivisSpeech にインストールする（AivisSpeech がダウンロードする。数分かかる）。"""
        try:
            response = await self._client.post(
                "/aivm_models/install",
                files={"url": (None, url)},
                timeout=httpx.Timeout(connect=5.0, read=1800.0, write=30.0, pool=5.0),
            )
        except httpx.TransportError as exc:
            raise unavailable() from exc
        if response.status_code not in (200, 204):
            raise TtsError("声の追加に失敗しました。時間をおいてもう一度お試しください。", "voice_install_failed", 502)
        self._speakers = None

    async def uninstall_model(self, aivm_uuid: str) -> None:
        try:
            response = await self._client.delete(f"/aivm_models/{aivm_uuid}/uninstall")
        except httpx.TransportError as exc:
            raise unavailable() from exc
        if response.status_code not in (200, 204):
            raise TtsError("声を削除できませんでした。", "voice_uninstall_failed", 502)
        self._speakers = None
