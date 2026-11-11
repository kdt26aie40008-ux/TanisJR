"""AivisHub（AivisSpeech の音声モデルの公開サイト）から声を探して追加する。

- 探す: AivisHub の公開 API で、声の種類（若い男性・おじさん・おじいちゃんなど）ごとに一覧を取る。
- 試聴: AivisHub が公開しているサンプル音声を、このアプリ経由で取り寄せて再生する
  （画面からはこのアプリにしか接続しないため。取り寄せる先は AivisHub の音声ファイルだけに限る）。
- 追加: AivisSpeech Engine にダウンロード用の URL を渡し、AivisSpeech がダウンロード・インストールする。
  会話の内容などの個人データは送らない。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from app.speech.tts import AivisClient, TtsError

logger = logging.getLogger(__name__)

HUB_API = "https://api.aivis-project.com"
# サンプル音声を取り寄せてよい場所（AivisHub の配信用サーバーだけ）
_SAMPLE_HOST = "assets.aivis-project.com"
_SAMPLE_MAX_BYTES = 5 * 1024 * 1024
_CACHE_SECONDS = 30 * 60
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_UUID = re.compile(UUID_PATTERN)

VoiceTimbre = Literal[
    "YoungMale",
    "YoungFemale",
    "YouthfulMale",
    "YouthfulFemale",
    "AdultMale",
    "AdultFemale",
    "MiddleAgedMale",
    "MiddleAgedFemale",
    "ElderlyMale",
    "ElderlyFemale",
    "Neutral",
    "Mechanical",
]

TIMBRE_LABELS: dict[str, str] = {
    "YoungMale": "男の子",
    "YoungFemale": "女の子",
    "YouthfulMale": "若い男性",
    "YouthfulFemale": "若い女性",
    "AdultMale": "大人の男性",
    "AdultFemale": "大人の女性",
    "MiddleAgedMale": "おじさん",
    "MiddleAgedFemale": "おばさん",
    "ElderlyMale": "おじいちゃん",
    "ElderlyFemale": "おばあちゃん",
    "Neutral": "中性的",
    "Mechanical": "機械っぽい",
}


class HubError(Exception):
    def __init__(self, message: str, code: str = "voice_hub_error", status: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _hub_unavailable() -> HubError:
    return HubError(
        "声の一覧（AivisHub）に接続できませんでした。インターネットの接続を確認してください。", "voice_hub_unavailable", 503
    )


def _summarize(model: dict[str, Any]) -> dict[str, Any] | None:
    """AivisHub のモデル情報から、画面に出す項目だけを取り出す。"""
    files = [f for f in model.get("model_files") or [] if f.get("model_type") == "AIVMX"]
    if not files:
        return None  # AivisSpeech で使える形式（AIVMX）がない
    aivmx = files[-1]
    samples: list[dict[str, str]] = []
    styles: list[str] = []
    for speaker in model.get("speakers") or []:
        for style in speaker.get("styles") or []:
            styles.append(str(style.get("name", "")))
            for sample in style.get("voice_samples") or []:
                if len(samples) < 3 and sample.get("audio_url"):
                    samples.append({"url": str(sample["audio_url"]), "transcript": str(sample.get("transcript", ""))})
    return {
        "aivm_uuid": str(model.get("aivm_model_uuid", "")),
        "name": str(model.get("name", "")),
        "description": str(model.get("description") or aivmx.get("description") or "")[:300],
        "creator": str((model.get("user") or {}).get("name", "")),
        "timbre": str(model.get("voice_timbre", "")),
        "timbre_label": TIMBRE_LABELS.get(str(model.get("voice_timbre", "")), "その他"),
        "styles": styles[:12],
        "license_type": str(aivmx.get("license_type") or ""),
        "file_size": int(aivmx.get("file_size") or 0),
        "downloads": int(model.get("total_download_count") or 0),
        "samples": samples,
    }


@dataclass
class InstallJob:
    state: Literal["installing", "done", "error"]
    aivm_uuid: str
    name: str
    error: str = ""
    started_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {"state": self.state, "aivm_uuid": self.aivm_uuid, "name": self.name, "error": self.error}


class VoiceHub:
    def __init__(self, tts: AivisClient, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._tts = tts
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0), transport=transport, follow_redirects=False
        )
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._known: dict[str, dict[str, Any]] = {}
        self.job: InstallJob | None = None
        self._task: asyncio.Task[None] | None = None

    async def aclose(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        await self._client.aclose()

    async def search(self, timbres: list[str]) -> list[dict[str, Any]]:
        key = ",".join(sorted(timbres))
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
            return cached[1]
        params: list[tuple[str, str | int]] = [("limit", 30), ("sort", "download")]
        params += [("voice_timbres", t) for t in timbres]
        try:
            response = await self._client.get(f"{HUB_API}/v1/aivm-models/search", params=params)
        except httpx.TransportError as exc:
            raise _hub_unavailable() from exc
        if response.status_code != 200:
            raise _hub_unavailable()
        items = [s for m in response.json().get("aivm_models", []) if (s := _summarize(m))]
        for item in items:
            self._known[item["aivm_uuid"]] = item
        self._cache[key] = (time.monotonic(), items)
        return items

    def known(self, aivm_uuid: str) -> dict[str, Any] | None:
        """一覧で見たことのあるモデル（追加・試聴は、一覧に出たものだけ受け付ける）。"""
        return self._known.get(aivm_uuid)

    async def sample(self, aivm_uuid: str, index: int) -> bytes:
        model = self.known(aivm_uuid)
        if model is None or not 0 <= index < len(model["samples"]):
            raise HubError("試聴できる音声が見つかりません。一覧を開き直してください。", "voice_sample_not_found", 404)
        url = model["samples"][index]["url"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != _SAMPLE_HOST:
            raise HubError("試聴できる音声が見つかりません。", "voice_sample_not_found", 404)
        try:
            response = await self._client.get(url)
        except httpx.TransportError as exc:
            raise _hub_unavailable() from exc
        if response.status_code != 200 or len(response.content) > _SAMPLE_MAX_BYTES:
            raise HubError("試聴の音声を取得できませんでした。", "voice_sample_failed", 502)
        return response.content

    def start_install(self, aivm_uuid: str) -> InstallJob:
        if not _UUID.match(aivm_uuid):
            raise HubError("声の指定が正しくありません。", "voice_not_found", 404)
        if self.job and self.job.state == "installing":
            raise HubError("ほかの声を追加しているところです。終わるまでお待ちください。", "voice_install_busy", 409)
        model = self.known(aivm_uuid)
        if model is None:
            raise HubError("追加する声が見つかりません。一覧を開き直してください。", "voice_not_found", 404)
        self.job = InstallJob(state="installing", aivm_uuid=aivm_uuid, name=model["name"])
        self._task = asyncio.create_task(self._install(self.job))
        return self.job

    async def _install(self, job: InstallJob) -> None:
        url = f"{HUB_API}/v1/aivm-models/{job.aivm_uuid}/download?model_type=AIVMX"
        try:
            await self._tts.install_model(url)
            job.state = "done"
        except TtsError as exc:
            job.state, job.error = "error", exc.message
        except Exception as exc:  # noqa: BLE001  画面に失敗を伝えるため
            logger.error("Voice install failed: %s", type(exc).__name__)
            job.state, job.error = "error", "声の追加に失敗しました。"
