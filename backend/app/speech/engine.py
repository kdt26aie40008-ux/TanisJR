"""AivisSpeech Engine の自動起動。

AivisSpeech のアプリ画面を開かなくても、エンジン（run.exe）だけを画面なしで起動して読み上げを使えるようにする。
アプリ画面が起動するときと同じ引数（--host 127.0.0.1 --port 10101）で起動する。
エンジンは同時に1つしか動かせない（ログファイルを専有する）ため、応答がないときだけ起動する。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from app.speech.tts import AivisClient, TtsError

logger = logging.getLogger(__name__)

STARTUP_TIMEOUT_SECONDS = 120


def default_engine_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "AivisSpeech" / "AivisSpeech-Engine" / "run.exe"


class EngineLauncher:
    def __init__(self, client: AivisClient, base_url: str, engine_path: Path | None = None) -> None:
        self.client = client
        parsed = urlparse(base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 10101
        self.engine_path = engine_path or default_engine_path()
        self._starting: asyncio.Task | None = None
        self.started_at: float | None = None
        self.last_error: str | None = None

    def installed(self) -> bool:
        return self.engine_path.is_file()

    async def running(self) -> bool:
        try:
            await self.client.version()
            return True
        except TtsError:
            return False

    @property
    def starting(self) -> bool:
        return self._starting is not None and not self._starting.done()

    def _spawn(self) -> None:
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(  # noqa: S603  インストール済みのエンジンを固定の引数で起動する
            [str(self.engine_path), "--host", self.host, "--port", str(self.port)],
            cwd=str(self.engine_path.parent),
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    async def _start_and_wait(self) -> bool:
        if await self.running():
            return True
        if not self.installed():
            self.last_error = "AivisSpeech がインストールされていません。"
            return False
        logger.info("Starting AivisSpeech Engine in the background")
        self._spawn()
        self.started_at = time.time()
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            if await self.running():
                self.last_error = None
                logger.info("AivisSpeech Engine is ready")
                return True
        self.last_error = "AivisSpeech の起動に時間がかかっています。しばらく待ってから再度お試しください。"
        return False

    def ensure_started(self) -> None:
        """エンジンが動いていなければ、バックグラウンドで起動を始める（待たない）。"""
        if not self.starting:
            self._starting = asyncio.create_task(self._start_and_wait())

    async def wait_ready(self) -> bool:
        self.ensure_started()
        assert self._starting is not None
        return await self._starting
