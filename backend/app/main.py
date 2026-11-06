"""FastAPI アプリケーションの生成。

起動: python -m app.main  （127.0.0.1 のみで待ち受ける）
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.backup import BackupError
from app.config import LEGACY_DATA_DIR, Config, load_config
from app.data_location import apply_start_fresh, migrate_legacy_data
from app.crypto import CryptoError, DataLocked, DpapiProtector, KeyStore, Protector, Vault
from app.db import Database
from app.deps import Services
from app.llm.ollama import OllamaClient
from app.repositories.conversations import ConversationRepository
from app.repositories.memories import MemoryRepository
from app.repositories.profile import ProfileRepository
from app.repositories.settings import SettingsRepository
from app.avatars import AvatarStore
from app.calendar.google import GoogleClient, GoogleError
from app.calendar.service import CalendarError, CalendarService
from app.notify.scheduler import NotificationScheduler
from app.notify.toast import Notifier, WindowsToastNotifier
from app.routers import assistant, avatars, chat, data, health, models, settings, setup, speech
from app.routers import calendar as calendar_router
from app.routers import system as system_router
from app.routers import training as training_router
from app.routers import scene as scene_router
from app.backgrounds import BackgroundStore
from app.services.weather import WeatherService
from app.training.data import TrainingDataRepository
from app.training.runner import TrainingManager
from app.routers import memories as memories_router
from app.security import OriginCheckMiddleware
from app.services.data_protection import unlock
from app.services.memory import MemoryService
from app.speech.engine import EngineLauncher
from app.speech.stt import Transcriber, WhisperService
from app.speech.tts import AivisClient
from app.vector_index import VectorIndex

logger = logging.getLogger("twin")

_FIELD_LABELS = {
    "answers": "回答",
    "ai_name": "AIの名前",
    "messages": "メッセージ",
    "content": "内容",
    "model": "モデル名",
    "fallback_model": "代替モデル名",
    "temperature": "温度",
    "num_ctx": "コンテキスト長",
    "category": "カテゴリ",
    "importance": "重要度",
    "passphrase": "パスフレーズ",
    "rag_max_results": "記憶の参照件数",
    "rag_max_distance": "関連度のしきい値",
    "embedding_model": "記憶検索用モデル",
    "conversation_id": "会話ID",
    "memory_id": "記憶ID",
    "summary": "予定のタイトル",
    "start": "開始日時",
    "end": "終了日時",
    "location": "場所",
    "reminder_minutes": "リマインダー",
    "event_id": "予定ID",
    "minutes": "通知時刻",
    "default_reminder_minutes": "通知の既定時刻",
}


def create_app(
    config: Config | None = None,
    ollama_transport: httpx.AsyncBaseTransport | None = None,
    protector: Protector | None = None,
    aivis_transport: httpx.AsyncBaseTransport | None = None,
    transcriber: Transcriber | None = None,
    google_transport: httpx.AsyncBaseTransport | None = None,
    notifier: Notifier | None = None,
    startup_dir: Path | None = None,
    start_scheduler: bool = True,
    allow_process_control: bool = True,
    background: bool = False,
    aivis_engine_path: Path | None = None,
    weather_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    config = config or load_config()
    db = Database(config.db_path)
    db.migrate()
    vault = Vault()
    settings_repo = SettingsRepository(db)
    conversations = ConversationRepository(db, vault)
    memories = MemoryRepository(db, vault)
    ollama = OllamaClient(config.ollama_url, transport=ollama_transport)
    index = VectorIndex(config.data_dir / "chroma")
    google = GoogleClient(transport=google_transport)
    calendar = CalendarService(db, vault, settings_repo, google, config.google_client_file)
    notifier = notifier or WindowsToastNotifier()
    training_data = TrainingDataRepository(db, vault, conversations)
    tts = AivisClient(config.aivis_url, transport=aivis_transport)
    services = Services(
        config=config,
        db=db,
        vault=vault,
        keystore=KeyStore(config.data_dir / "keys" / "master.key", protector or DpapiProtector()),
        settings=settings_repo,
        profile=ProfileRepository(db, vault),
        conversations=conversations,
        memories=memories,
        memory=MemoryService(db, memories, conversations, settings_repo, ollama, index),
        index=index,
        ollama=ollama,
        stt=transcriber or WhisperService(config.models_dir / "whisper"),
        tts=tts,
        tts_engine=EngineLauncher(tts, config.aivis_url, aivis_engine_path),
        avatars=AvatarStore(db, config.data_dir / "avatars"),
        google=google,
        calendar=calendar,
        notifier=notifier,
        training_data=training_data,
        training=TrainingManager(
            db, vault, settings_repo, training_data, ollama, config.data_dir / "training" / "runs", config.models_dir
        ),
        weather=WeatherService(transport=weather_transport),
        backgrounds=BackgroundStore(config.data_dir / "backgrounds"),
        scheduler=NotificationScheduler(db, settings_repo, calendar, notifier),
        startup_dir=startup_dir,
        allow_process_control=allow_process_control,
        background=background,
    )
    unlock(services.vault, services.keystore, services.settings, services.profile)
    if vault.locked:
        logger.warning("データがロックされています: %s", vault.locked_reason)
    else:
        # 前回のサーバー停止で中断された学習を片付ける（平文の一時ファイルも削除）
        services.training.recover_interrupted()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks: list[asyncio.Task] = []
        if not vault.locked:
            # 起動時に SQLite と ChromaDB の整合性を確認する（Ollama 待ちで起動を遅らせない）
            tasks.append(asyncio.create_task(_startup_reconcile(services)))
            if start_scheduler and services.scheduler:
                # 予定の通知（再起動後も DB の状態から再開する）
                tasks.append(asyncio.create_task(services.scheduler.run_forever()))
            settings_now = services.settings.get()
            if start_scheduler and settings_now.tts_engine_autostart and settings_now.tts_speaker is not None:
                # 読み上げを使う設定なら、AivisSpeech のアプリを開かなくてもエンジンを起動しておく
                services.tts_engine.ensure_started()
        yield
        for task in tasks:
            task.cancel()
        await services.ollama.aclose()
        await services.tts.aclose()
        await services.google.aclose()
        await services.weather.aclose()

    app = FastAPI(title="AnotherMe", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.services = services

    # 後に追加したものが外側になる: Host検証 → Origin検証 → ルーター
    app.add_middleware(OriginCheckMiddleware, allowed_origins=config.allowed_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_input", "message": _validation_message(exc)}})

    @app.exception_handler(DataLocked)
    async def _locked(_: Request, exc: DataLocked) -> JSONResponse:
        return JSONResponse(status_code=423, content={"detail": {"code": "data_locked", "message": str(exc)}})

    @app.exception_handler(CryptoError)
    async def _crypto(_: Request, exc: CryptoError) -> JSONResponse:
        logger.error("Crypto error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": {"code": "crypto_error", "message": str(exc)}})

    @app.exception_handler(BackupError)
    async def _backup(_: Request, exc: BackupError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": {"code": "backup_error", "message": str(exc)}})

    @app.exception_handler(GoogleError)
    async def _google(_: Request, exc: GoogleError) -> JSONResponse:
        logger.warning("Google API error: %s", exc.code)
        return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(CalendarError)
    async def _calendar(_: Request, exc: CalendarError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # 本文や個人情報を含みうるため、例外の型のみ記録する
        logger.error("Unexpected error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"detail": {"code": "internal_error", "message": "予期しないエラーが発生しました。もう一度お試しください。"}},
        )

    for module in (
        health, setup, chat, settings, models, memories_router, data, speech, avatars, calendar_router, system_router, training_router,
        assistant, scene_router,
    ):
        app.include_router(module.router)

    _mount_frontend(app, config.frontend_dist)
    return app


async def _startup_reconcile(services: Services) -> None:
    try:
        result = await services.memory.reconcile()
        logger.info("記憶索引の整合性確認: %s", result)
    except Exception as exc:  # noqa: BLE001
        logger.warning("記憶索引の整合性確認に失敗しました: %s", type(exc).__name__)


def _validation_message(exc: RequestValidationError) -> str:
    for error in exc.errors():
        ctx_error = (error.get("ctx") or {}).get("error")
        # field_validator で投げた日本語メッセージを優先して表示する
        if isinstance(ctx_error, ValueError) and str(ctx_error):
            return str(ctx_error)
        loc = [str(p) for p in error.get("loc", ()) if p != "body"]
        field = next((_FIELD_LABELS[p] for p in reversed(loc) if p in _FIELD_LABELS), None)
        if field:
            return f"{field}の値が正しくありません。"
    return "入力内容が正しくありません。"


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """ビルド済みフロントエンドを配信する（SPA のため未知のパスは index.html を返す）。"""
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):  # noqa: ANN202
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": {"code": "not_found", "message": "見つかりません。"}})
        index = root / "index.html"
        if not index.is_file():
            return JSONResponse(
                status_code=503,
                content={"detail": {"code": "frontend_not_built", "message": "画面がビルドされていません。scripts\\start.ps1 で起動してください。"}},
            )
        candidate = (root / path).resolve()
        # ディレクトリトラバーサル対策: dist 配下のファイルのみ返す
        if path and candidate.is_file() and candidate.is_relative_to(root):
            # PWA: マニフェストの種類を明示し、サービスワーカーは更新がすぐ届くようキャッシュさせない
            if candidate.suffix == ".webmanifest":
                return FileResponse(candidate, media_type="application/manifest+json")
            if path == "sw.js":
                return FileResponse(candidate, media_type="text/javascript", headers={"Cache-Control": "no-cache"})
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-store"})


LOG_MAX_BYTES = 5 * 1024 * 1024


def _redirect_output_to_log(data_dir: Path) -> None:
    """バックグラウンド（pythonw）ではコンソールが無いので、ログをファイルに書く。本文は元々出力しない。"""
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "server.log"
    if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
        path.replace(path.with_suffix(".log.1"))
    stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115  プロセス終了まで開いたまま使う
    sys.stdout = sys.stderr = stream


def main() -> None:
    import argparse

    import uvicorn

    from app.system import wait_for_port_free

    parser = argparse.ArgumentParser(description="AnotherMe サーバー")
    parser.add_argument("--background", action="store_true", help="コンソールなしで動かし、ログをファイルに書く")
    parser.add_argument("--wait-for-port", action="store_true", help="再起動時、前のプロセスの終了を待つ")
    args = parser.parse_args()

    config = load_config()
    # 再起動時は前のプロセスの終了を待つ（前のプロセスが開いているファイルは移動できないため、データの退避より先に行う）
    if args.wait_for_port and not wait_for_port_free(config.port):
        print(f"ポート {config.port} が使用中のため起動できません", file=sys.stderr)
        sys.exit(1)
    # データの移動・退避は、ログファイルなどを開く前に行う（開いているファイルは Windows で移動できない）
    startup_notes: list[str] = []
    if not os.environ.get("TWIN_DATA_DIR"):
        result = migrate_legacy_data(LEGACY_DATA_DIR, config.data_dir, DpapiProtector())
        startup_notes.append(f"以前の保存先の確認: {result}")
    archived = apply_start_fresh(config.data_dir)
    if archived:
        startup_notes.append(f"以前のデータを {archived.name} に退避し、新しく始めました")
    if args.background or sys.stderr is None:
        _redirect_output_to_log(config.data_dir)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    for note in startup_notes:
        logger.info(note)
    logger.info("データ保存先: %s", config.data_dir)
    logger.info("http://127.0.0.1:%d で起動します", config.port)
    # 外部からの接続を受けないよう 127.0.0.1 に固定する
    uvicorn.run(
        create_app(config, background=args.background),
        host="127.0.0.1",
        port=config.port,
        log_level="info",
        # バックグラウンド時は uvicorn 独自のログ設定を使わず、上の設定（ファイル出力）に従う
        log_config=None if args.background else uvicorn.config.LOGGING_CONFIG,
    )


if __name__ == "__main__":
    main()
