"""音声認識（faster-whisper）と音声合成（AivisSpeech）。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request
from fastapi.responses import Response

from app.deps import Services, get_services
from app.errors import AppError
from app.schemas import AppSettings, SpeakerAck, TtsRequest, VoiceInstallRequest, WhisperDownloadRequest
from app.speech.stt import MAX_AUDIO_BYTES, SttError
from app.speech.tts import TtsError, VoiceTune, clean_for_speech
from app.speech.voice_hub import TIMBRE_LABELS, UUID_PATTERN, HubError, VoiceTimbre

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
async def transcribe(request: Request, fast: bool = False, services: Services = Depends(get_services)) -> dict:
    """録音した音声（webm/opus, wav 等）を受け取り、文字に起こす。音声は保存しない。

    fast=true は呼びかけ（「ねえ○○」）の検出用で、精度より速さを優先する。
    """
    audio = await read_limited(request, MAX_AUDIO_BYTES)
    if not audio:
        raise AppError(400, "empty_audio", "音声が空です。もう一度録音してください。")
    settings = services.settings.get()
    # 呼びかけの聞き取りでは、AI の名前（と読み）を聞き取りやすくする
    hotwords = " ".join(n for n in (settings.wake_reading, settings.ai_name) if n and n.strip()) if fast else None
    try:
        result = await services.stt.transcribe(
            audio, settings.stt_model, settings.stt_device, language=settings.language, fast=fast,
            hotwords=hotwords or None,
        )
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


def _engine_info(services: Services) -> dict:
    return {
        "installed": services.tts_engine.installed(),
        "starting": services.tts_engine.starting,
        "autostart": services.settings.get().tts_engine_autostart,
    }


@router.get("/tts/speakers")
async def speakers(services: Services = Depends(get_services)) -> dict:
    settings = services.settings.get()
    try:
        items = await services.tts.speakers()
    except TtsError as exc:
        message = exc.message
        if settings.tts_engine_autostart and services.tts_engine.installed():
            # AivisSpeech のアプリを開いていなくても、エンジンだけを画面なしで起動する
            services.tts_engine.ensure_started()
            message = "読み上げエンジン（AivisSpeech）を起動しています。1分ほどお待ちください。"
        return {
            "available": False, "message": message, "speakers": [], "selected": settings.tts_speaker,
            "engine": _engine_info(services),
        }
    acknowledged = set(settings.tts_acknowledged_speakers)
    return {
        "available": True,
        "message": None,
        "speakers": [{**s, "acknowledged": s["speaker_uuid"] in acknowledged} for s in items],
        "selected": settings.tts_speaker,
        "engine": _engine_info(services),
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


def resolve_voice(body: TtsRequest, settings: AppSettings) -> tuple[int | None, VoiceTune]:
    """読み上げに使う声（スタイル id と調整）を決める。

    試聴中の調整 → 試聴する元の声 → 設定で選んだ「作った声」→ 設定で選んだ元の声、の順。
    """
    if body.tune is not None:
        t = body.tune
        return t.style_id, VoiceTune(t.speed, t.pitch, t.intonation, t.tempo, t.volume)
    if body.speaker is not None:
        return body.speaker, VoiceTune(speed=settings.tts_speed)
    custom = next((v for v in settings.tts_custom_voices if v.id == settings.tts_voice), None)
    if custom is not None:
        return custom.style_id, VoiceTune(custom.speed, custom.pitch, custom.intonation, custom.tempo, custom.volume)
    return settings.tts_speaker, VoiceTune(speed=settings.tts_speed)


@router.post("/tts")
async def synthesize(body: TtsRequest, services: Services = Depends(get_services)) -> Response:
    settings = services.settings.get()
    style_id, tune = resolve_voice(body, settings)
    if style_id is None:
        raise AppError(409, "tts_speaker_not_selected", "読み上げの声が選択されていません。設定画面で選択してください。")
    text = clean_for_speech(body.text)
    if not text:
        raise AppError(400, "empty_text", "読み上げる文章がありません。")
    if settings.tts_engine_autostart and services.tts_engine.installed() and not await services.tts_engine.running():
        # エンジンが止まっていれば起動して、準備ができるまで待つ（初回のみ1分程度）
        if not await services.tts_engine.wait_ready():
            raise AppError(503, "tts_starting", services.tts_engine.last_error or "読み上げエンジンを起動できませんでした。")
    try:
        speaker_uuid = await services.tts.speaker_uuid_for_style(style_id)
        if speaker_uuid is None:
            raise AppError(404, "speaker_not_found", "選択された声が見つかりません。設定画面で選び直してください。")
        if speaker_uuid not in settings.tts_acknowledged_speakers:
            raise AppError(
                409, "tts_license_not_acknowledged", "この声の利用規約が未確認です。設定画面で利用規約を確認してください。"
            )
        audio = await services.tts.synthesize(text, style_id, tune)
    except TtsError as exc:
        raise _tts_error(exc) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# ---------- 声を増やす（AivisHub から追加） ----------


def _hub_error(exc: HubError) -> AppError:
    return AppError(exc.status, exc.code, exc.message)


@router.get("/voices/hub")
async def hub_voices(
    timbre: list[VoiceTimbre] = Query(default=[]), services: Services = Depends(get_services)
) -> dict:
    """AivisHub の声の一覧（声の種類で絞り込める）。追加済みかどうかも返す。"""
    try:
        items = await services.voice_hub.search(list(timbre))
    except HubError as exc:
        raise _hub_error(exc) from exc
    try:
        installed = {m["aivm_uuid"] for m in await services.tts.installed_models()}
    except TtsError:
        installed = set()
    return {
        "timbres": [{"id": k, "label": v} for k, v in TIMBRE_LABELS.items()],
        "voices": [{**v, "installed": v["aivm_uuid"] in installed} for v in items],
    }


@router.get("/voices/hub/{aivm_uuid}/sample/{index}")
async def hub_sample(
    index: int, aivm_uuid: str = Path(pattern=UUID_PATTERN), services: Services = Depends(get_services)
) -> Response:
    try:
        audio = await services.voice_hub.sample(aivm_uuid, index)
    except HubError as exc:
        raise _hub_error(exc) from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.get("/voices/installed")
async def installed_voices(services: Services = Depends(get_services)) -> dict:
    try:
        models = await services.tts.installed_models()
    except TtsError as exc:
        raise _tts_error(exc) from exc
    return {"models": models, "job": services.voice_hub.job.public() if services.voice_hub.job else None}


@router.post("/voices/install", status_code=202)
async def install_voice(body: VoiceInstallRequest, services: Services = Depends(get_services)) -> dict:
    if not body.confirmed:
        raise AppError(400, "confirmation_required", "ダウンロードの容量と入手元を確認してください。")
    try:
        await services.tts.version()
    except TtsError as exc:
        raise _tts_error(exc) from exc
    try:
        job = services.voice_hub.start_install(body.aivm_uuid)
    except HubError as exc:
        raise _hub_error(exc) from exc
    return {"job": job.public()}


@router.delete("/voices/{aivm_uuid}")
async def uninstall_voice(aivm_uuid: str = Path(pattern=UUID_PATTERN), services: Services = Depends(get_services)) -> dict:
    try:
        models = await services.tts.installed_models()
        if not any(m["aivm_uuid"] == aivm_uuid for m in models):
            raise AppError(404, "voice_not_found", "その声は追加されていません。")
        if len(models) <= 1:
            raise AppError(409, "last_voice", "最後の1つの声は削除できません。")
        await services.tts.uninstall_model(aivm_uuid)
    except TtsError as exc:
        raise _tts_error(exc) from exc
    return {"removed": True}
