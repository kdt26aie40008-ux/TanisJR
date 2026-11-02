"""AivisSpeech Engine（VOICEVOX 互換 API）による音声合成。"""

from __future__ import annotations

import re
import time
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

    async def synthesize(self, text: str, style_id: int, speed: float) -> bytes:
        query = (await self._request("POST", "/audio_query", params={"text": text, "speaker": style_id})).json()
        query["speedScale"] = speed
        response = await self._request("POST", "/synthesis", params={"speaker": style_id}, json=query)
        return response.content
