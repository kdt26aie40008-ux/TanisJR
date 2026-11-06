"""Windows デスクトップ通知（トースト）。

追加ライブラリを使わず、Windows PowerShell から WinRT の通知 API を呼ぶ。
件名などの文字列はコマンドに埋め込まず環境変数で渡し、XML はエスケープする（コマンド注入の防止）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

# 通知の送信元として Windows PowerShell の AppUserModelID を使う（独自IDの登録には別途ショートカット作成が必要なため）
APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$title = [Security.SecurityElement]::Escape($env:TWIN_TOAST_TITLE)
$body = [Security.SecurityElement]::Escape($env:TWIN_TOAST_BODY)
$app = [Security.SecurityElement]::Escape($env:TWIN_TOAST_APPNAME)
$close = [Security.SecurityElement]::Escape($env:TWIN_TOAST_CLOSE)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text><text placement='attribution'>$app</text></binding></visual><actions><action content='$close' arguments='dismiss' activationType='system'/></actions><audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:TWIN_TOAST_APPID).Show($toast)
"""


class Notifier(Protocol):
    async def notify(self, title: str, body: str) -> bool: ...


class WindowsToastNotifier:
    def __init__(self, powershell: Path = POWERSHELL) -> None:
        self.powershell = powershell

    def _run(self, title: str, body: str) -> bool:
        if sys.platform != "win32" or not self.powershell.exists():
            logger.warning("Desktop notifications are only available on Windows")
            return False
        # スクリプト本体は ASCII のみにし、日本語は環境変数で渡す（PowerShell 5.1 の標準入力の文字コード対策）
        env = {
            **os.environ,
            "TWIN_TOAST_TITLE": title[:100],
            "TWIN_TOAST_BODY": body[:250],
            "TWIN_TOAST_APPID": APP_ID,
            "TWIN_TOAST_APPNAME": "AnotherMe",
            "TWIN_TOAST_CLOSE": "閉じる",
        }
        result = subprocess.run(
            [str(self.powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", "-"],
            input=_SCRIPT.encode("utf-8"),
            env=env,
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            logger.warning("Toast notification failed (exit %s)", result.returncode)
        return result.returncode == 0

    async def notify(self, title: str, body: str) -> bool:
        return await asyncio.to_thread(self._run, title, body)
