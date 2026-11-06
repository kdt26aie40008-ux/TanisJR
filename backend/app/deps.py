"""ルーターから共有オブジェクトを取得するための依存関数。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from app.avatars import AvatarStore
from app.backgrounds import BackgroundStore
from app.services.weather import WeatherService
from app.calendar.google import GoogleClient
from app.calendar.service import CalendarService
from app.notify.scheduler import NotificationScheduler
from app.notify.toast import Notifier
from app.training.data import TrainingDataRepository
from app.training.runner import TrainingManager
from app.config import Config
from app.speech.stt import Transcriber
from app.speech.engine import EngineLauncher
from app.speech.tts import AivisClient
from app.crypto import KeyStore, Vault
from app.db import Database
from app.llm.ollama import OllamaClient
from app.repositories.conversations import ConversationRepository
from app.repositories.memories import MemoryRepository
from app.repositories.profile import ProfileRepository
from app.repositories.settings import SettingsRepository
from app.services.memory import MemoryService
from app.vector_index import VectorIndex


@dataclass
class Services:
    config: Config
    db: Database
    vault: Vault
    keystore: KeyStore
    settings: SettingsRepository
    profile: ProfileRepository
    conversations: ConversationRepository
    memories: MemoryRepository
    memory: MemoryService
    index: VectorIndex
    ollama: OllamaClient
    stt: Transcriber
    tts: AivisClient
    tts_engine: EngineLauncher
    avatars: AvatarStore
    google: GoogleClient
    calendar: CalendarService
    notifier: Notifier
    training_data: TrainingDataRepository
    training: TrainingManager
    weather: WeatherService
    backgrounds: BackgroundStore
    scheduler: NotificationScheduler | None = None
    # None は実際のスタートアップフォルダー（テストでは一時フォルダーを渡す）
    startup_dir: Path | None = None
    # 画面からの停止・再起動を許可するか（テストでは無効）
    allow_process_control: bool = True
    background: bool = False


def get_services(request: Request) -> Services:
    return request.app.state.services
