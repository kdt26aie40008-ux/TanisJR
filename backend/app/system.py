"""バックグラウンドサービスの自動起動・停止・再起動。

自動起動は、ユーザーのスタートアップフォルダーにショートカットを置く方式（管理者権限不要）。
起動するのはサーバーのみで、ブラウザーは開かない。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from app.config import REPO_ROOT
from app.notify.toast import POWERSHELL

SHORTCUT_NAME = "PersonalTwinAI.lnk"
BACKEND_DIR = REPO_ROOT / "backend"


class AutostartError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def background_python() -> Path:
    """コンソール画面を出さない pythonw.exe（なければ通常の python）。"""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def autostart_enabled(directory: Path | None = None) -> bool:
    return ((directory or startup_dir()) / SHORTCUT_NAME).is_file()


_SHORTCUT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($env:TWIN_LNK_PATH)
$lnk.TargetPath = $env:TWIN_LNK_TARGET
$lnk.Arguments = $env:TWIN_LNK_ARGS
$lnk.WorkingDirectory = $env:TWIN_LNK_WORKDIR
$lnk.WindowStyle = 7
$lnk.Description = $env:TWIN_LNK_DESC
$lnk.Save()
"""


def enable_autostart(directory: Path | None = None) -> Path:
    directory = directory or startup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SHORTCUT_NAME
    env = {
        **os.environ,
        "TWIN_LNK_PATH": str(path),
        "TWIN_LNK_TARGET": str(background_python()),
        "TWIN_LNK_ARGS": "-m app.main --background",
        "TWIN_LNK_WORKDIR": str(BACKEND_DIR),
        "TWIN_LNK_DESC": "Personal Twin AI background service",
    }
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", "-"],
        input=_SHORTCUT_SCRIPT.encode("ascii"),
        env=env,
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0 or not path.is_file():
        raise AutostartError("自動起動の設定に失敗しました。")
    return path


def disable_autostart(directory: Path | None = None) -> None:
    ((directory or startup_dir()) / SHORTCUT_NAME).unlink(missing_ok=True)


def wait_for_port_free(port: int, timeout: float = 20.0) -> bool:
    """再起動時、前のプロセスがポートを解放するまで待つ。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.5)
    return False


def spawn_background_server() -> None:
    """新しいバックグラウンドサーバーを起動する（親プロセスから切り離す）。"""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(  # noqa: S603  自分自身の Python で app.main を起動するだけ
        [str(background_python()), "-m", "app.main", "--background", "--wait-for-port"],
        cwd=str(BACKEND_DIR),
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
