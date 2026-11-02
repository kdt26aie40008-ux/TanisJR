"""音声認識（faster-whisper）と音声合成（AivisSpeech）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import Response

from app.deps import Services, get_services
from app.errors import AppError
from app.schemas import SpeakerAck, TtsRequest, WhisperDownloadRequest
from app.speech.stt import MAX_AUDIO_BYTES, SttError
from app.speech.tts import TtsError, clean_for_speech

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/speech", tags=["speech"])


async def read_limited(request: Request, limit: int) -> bytes:
    too_large = AppError(413, "too_large", "データが大きすぎます。")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise too_large
    return bytes(body)


def _stt_error(exc: SttError) -> AppError:
    return AppError(exc.status, exc.code, exc.message)


def _tts_error(exc: TtsError) -> AppError:
    return AppError(exc.status, exc.code, exc.message)


# ---------- 音声認識 ----------


@router.get("/stt/status")
def stt_status(services: Services = Depends(get_services)) -> dict:
    # 同期関数なのでワーカースレッドで実行される（モデル確認でイベントループを止めない）
    settings = services.settings.get()
    return {**services.stt.status(), "model": settings.stt_model, "device": settings.stt_device}


@router.post("/stt/models/download", status_code=202)
def download_whisper(body: WhisperDownloadRequest, services: Services = Depends(get_services)) -> dict:
    if not body.confirmed:
        raise AppError(400, "confirmation_required", "ダウンロードの前に容量と保存先を確認してください。")
    try:
        services.stt.start_download(body.model)
    except SttError as exc:
        raise _stt_error(exc) from exc
    return {"started": True}


@router.post("/stt/warmup", status_code=202)
async def warmup(background: BackgroundTasks, services: Services = Depends(get_services)) -> dict:
    """モデルの読み込みを先に始める（初回認識の待ち時間を減らす）。結果は待たない。"""
    settings = services.settings.get()

    async def run() -> None:
        try:
            await services.stt.warmup(settings.stt_model, settings.stt_device)
        except Exception as exc:  # noqa: BLE001  失敗しても実際の認識時にエラーを表示する
            logger.warning("Whisper warmup failed: %s", type(exc).__name__)

    background.add_task(run)
    return {"started": True}


@router.post("/stt")
async def transcribe(request: Request, services: Services = Depends(get_services)) -> dict:
    """録音した音声（webm/opus, wav 等）を受け取り、文字に起こす。音声は保存しない。"""
    audio = await read_limited(request, MAX_AUDIO_BYTES)
    if not audio:
        raise AppError(400, "empty_audio", "音声が空です。もう一度録音してください。")
    settings = services.settings.get()
    try:
        result = await services.stt.transcribe(audio, settings.stt_model, settings.stt_device)
    except SttError as exc:
        raise _stt_error(exc) from exc
    return {
        "text": result.text,
        "duration": result.duration,
        "elapsed": result.elapsed,
        "device": result.device,
        "notice": result.notice,
    }


# ---------- 音声合成 ----------


@router.get("/tts/speakers")
async def speakers(services: Services = Depends(get_services)) -> dict:
    settings = services.settings.get()
    try:
        items = await services.tts.speakers()
    except TtsError as exc:
        return {"available": False, "message": exc.message, "speakers": [], "selected": settings.tts_speaker}
    acknowledged = set(settings.tts_acknowledged_speakers)
    return {
        "available": True,
        "message": None,
        "speakers": [{**s, "acknowledged": s["speaker_uuid"] in acknowledged} for s in items],
        "selected": settings.tts_speaker,
    }


@router.get("/tts/speakers/{speaker_uuid}/policy")
async def policy(speaker_uuid: str, services: Services = Depends(get_services)) -> dict:
    try:
        known = {s["speaker_uuid"] for s in await services.tts.speakers()}
        if speaker_uuid not in known:
            raise AppError(404, "speaker_not_found", "指定された話者が見つかりません。")
        return {"policy": await services.tts.policy(speaker_uuid)}
    except TtsError as exc:
        raise _tts_error(exc) from exc


@router.post("/tts/acknowledge")
async def acknowledge(body: SpeakerAck, services: Services = Depends(get_services)) -> dict:
    try:
        known = {s["speaker_uuid"] for s in await services.tts.speakers()}
    except TtsError as exc:
        raise _tts_error(exc) from exc
    if body.speaker_uuid not in known:
        raise AppError(404, "speaker_not_found", "指定された話者が見つかりません。")
    current = services.settings.get().tts_acknowledged_speakers
    if body.speaker_uuid not in current:
        services.settings.update({"tts_acknowledged_speakers": [*current, body.speaker_uuid]})
    return {"acknowledged": True}


@router.post("/tts")
async def synthesize(body: TtsRequest, services: Services = Depends(get_services)) -> Response:
    settings = services.settings.get()
    style_id = body.speaker if body.speaker is not None else settings.tts_speaker
    if style_id is None:
        raise AppError(409, "tts_speaker_not_selected", "読み上げの声が選択されていません。設定画面で選択してください。")
    text = clean_for_speech(body.text)
    if not text:
        raise AppError(400, "empty_text", "読み上げる文章がありません。")
    try:
        speaker_uuid = await services.tts.speaker_uuid_for_style(style_id)
        if speaker_uuid is None:
            raise AppError(404, "speaker_not_found", "選択された声が見つかりません。設定画面で選び直してください。")
        if speaker_uuid not in settings.tts_acknowledged_speakers:
            raise AppError(
                409, "tts_license_not_acknowledged", "この声の利用規約が未確認です。設定画面で利用規約を確認してください。"
            )
        audio = await services.tts.synthesize(text, style_id, settings.tts_speed)
    except TtsError as exc:
        raise _tts_error(exc) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
