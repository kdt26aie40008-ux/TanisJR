"""faster-whisper による日本語音声認識。

- 音声はメモリ上でデコード・認識し、ディスクにもログにも保存しない。
- 既定は CPU (int8)。GPU は LLM が使うため、CUDA は設定で明示した場合のみ使い、失敗時は CPU に戻す。
- モデルは models/whisper に保存し、推論時は local_files_only で外部通信しない。
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Hugging Face への利用状況送信を止める（モデルDL時のみ通信する）
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_AUDIO_SECONDS = 120


@dataclass(frozen=True)
class WhisperModelInfo:
    name: str
    size_gb: float
    description: str
    recommended: bool = False


WHISPER_CATALOG: tuple[WhisperModelInfo, ...] = (
    WhisperModelInfo("large-v3-turbo", 1.6, "高精度。CPUでは数秒〜10秒程度かかる", recommended=True),
    WhisperModelInfo("medium", 1.5, "精度と速度の中間"),
    WhisperModelInfo("small", 0.48, "速いが誤認識がやや多い"),
    WhisperModelInfo("base", 0.15, "最速・低精度（動作確認向け）"),
)


def find_model(name: str) -> WhisperModelInfo | None:
    return next((m for m in WHISPER_CATALOG if m.name == name), None)


class SttError(Exception):
    """ユーザーに表示できる日本語メッセージを持つ例外。"""

    def __init__(self, message: str, code: str = "stt_error", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


@dataclass
class Transcript:
    text: str
    duration: float
    elapsed: float
    device: str
    notice: str | None = None


def decode_audio(data: bytes, sampling_rate: int = 16000) -> Any:
    """任意の音声形式（webm/opus, wav, mp3 など）を 16kHz モノラル float32 に変換する（メモリ上のみ）。"""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=sampling_rate)
    chunks = []
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            if not container.streams.audio:
                raise SttError("音声が含まれていないファイルです。")
            for frame in container.decode(audio=0):
                chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
            chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    except SttError:
        raise
    except Exception as exc:  # noqa: BLE001  PyAV は多様な例外を投げる
        raise SttError("音声を読み取れませんでした。もう一度録音してください。") from exc
    if not chunks:
        raise SttError("音声が空です。もう一度録音してください。")
    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    if len(audio) > MAX_AUDIO_SECONDS * sampling_rate:
        raise SttError(f"音声が長すぎます（{MAX_AUDIO_SECONDS}秒まで）。")
    return audio


class Transcriber(Protocol):
    def status(self) -> dict[str, Any]: ...
    async def transcribe(self, audio: bytes, model: str, device: str) -> Transcript: ...
    async def warmup(self, model: str, device: str) -> bool: ...
    def start_download(self, model: str) -> None: ...


@dataclass
class _DownloadJob:
    model: str
    state: str = "downloading"  # downloading | done | error
    error: str | None = None
    started_at: float = field(default_factory=time.time)


class WhisperService:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._model: Any = None
        self._loaded: tuple[str, str] | None = None
        self._lock = asyncio.Lock()
        self._job: _DownloadJob | None = None

    # ---------- モデル管理 ----------

    def installed(self, name: str) -> bool:
        from faster_whisper import download_model

        try:
            download_model(name, cache_dir=str(self.models_dir), local_files_only=True)
            return True
        except Exception:  # noqa: BLE001  未取得時は huggingface_hub の例外
            return False

    def _downloaded_bytes(self) -> int:
        if not self.models_dir.exists():
            return 0
        return sum(p.stat().st_size for p in self.models_dir.rglob("*") if p.is_file())

    def status(self) -> dict[str, Any]:
        job = None
        if self._job:
            job = {**asdict(self._job), "downloaded_gb": round(self._downloaded_bytes() / 1024**3, 2)}
        return {
            "models": [{**asdict(m), "installed": self.installed(m.name)} for m in WHISPER_CATALOG],
            "models_dir": str(self.models_dir),
            "loaded": None if self._loaded is None else {"model": self._loaded[0], "device": self._loaded[1]},
            "download": job,
        }

    def start_download(self, model: str) -> None:
        if self._job and self._job.state == "downloading":
            raise SttError("別のモデルをダウンロード中です。完了までお待ちください。", "download_in_progress", 409)
        job = _DownloadJob(model)
        self._job = job

        def run() -> None:
            from faster_whisper import download_model

            try:
                self.models_dir.mkdir(parents=True, exist_ok=True)
                download_model(model, cache_dir=str(self.models_dir))
                job.state = "done"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Whisper model download failed: %s", type(exc).__name__)
                job.state = "error"
                job.error = "ダウンロードに失敗しました。インターネット接続と空き容量を確認してください。"

        threading.Thread(target=run, name="whisper-download", daemon=True).start()

    # ---------- 認識 ----------

    def _load(self, model: str, device: str) -> tuple[Any, str, str | None]:
        from faster_whisper import WhisperModel

        if self._loaded == (model, device):
            return self._model, device, None
        if not self.installed(model):
            raise SttError(
                f"音声認識モデル「{model}」がダウンロードされていません。設定画面からダウンロードしてください。",
                "stt_model_missing",
                409,
            )
        self._model = None
        notice = None
        loaded = None
        if device == "cuda":
            try:
                loaded = WhisperModel(
                    model, device="cuda", compute_type="int8_float16",
                    download_root=str(self.models_dir), local_files_only=True,
                )
            except Exception as exc:  # noqa: BLE001  CUDA ライブラリ未導入・GPU メモリ不足など
                logger.warning("CUDA unavailable for Whisper, falling back to CPU: %s", type(exc).__name__)
                notice = "GPUで音声認識できなかったため、CPUで処理しました。"
                device = "cpu"
        if loaded is None:
            loaded = WhisperModel(
                model, device="cpu", compute_type="int8",
                download_root=str(self.models_dir), local_files_only=True,
                cpu_threads=min(8, os.cpu_count() or 4),
            )
        self._model = loaded
        self._loaded = (model, device)
        return loaded, device, notice

    def _transcribe_sync(self, audio: bytes, model: str, device: str) -> Transcript:
        started = time.perf_counter()
        samples = decode_audio(audio)
        whisper, used_device, notice = self._load(model, device)
        try:
            segments, info = whisper.transcribe(
                samples, language="ja", beam_size=5, vad_filter=True, condition_on_previous_text=False
            )
            text = "".join(s.text for s in segments).strip()
        except RuntimeError as exc:
            if used_device != "cuda":
                raise
            # 推論時に GPU メモリ不足などで失敗した場合は CPU で再実行する
            logger.warning("Whisper CUDA inference failed: %s", type(exc).__name__)
            self._loaded = None
            whisper, used_device, _ = self._load(model, "cpu")
            notice = "GPUで音声認識できなかったため、CPUで処理しました。"
            segments, info = whisper.transcribe(
                samples, language="ja", beam_size=5, vad_filter=True, condition_on_previous_text=False
            )
            text = "".join(s.text for s in segments).strip()
        return Transcript(
            text=text, duration=round(info.duration, 2), elapsed=round(time.perf_counter() - started, 2),
            device=used_device, notice=notice,
        )

    def _warmup_sync(self, model: str, device: str) -> bool:
        import numpy as np

        # faster-whisper の初回 import やモデル確認も重いので、すべてワーカースレッドで行う
        if self._loaded == (model, device) or not self.installed(model):
            return False
        whisper, _, _ = self._load(model, device)
        # 初回推論は内部の初期化で遅いため、短い雑音で一度実行しておく
        noise = (np.random.default_rng(0).standard_normal(16000) * 0.01).astype(np.float32)
        list(whisper.transcribe(noise, language="ja", beam_size=1, vad_filter=False)[0])
        return True

    async def warmup(self, model: str, device: str) -> bool:
        """音声会話画面を開いたときに、モデルを先に読み込んでおく。"""
        if self._loaded == (model, device):
            return False
        async with self._lock:
            return await asyncio.to_thread(self._warmup_sync, model, device)

    async def transcribe(self, audio: bytes, model: str, device: str) -> Transcript:
        # モデルは1つだけ読み込み、同時実行しない（メモリ使用量を抑える）
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_sync, audio, model, device)
