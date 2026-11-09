"""スマホから使う（Tailscale 経由）。

- サーバーは今までどおり 127.0.0.1 だけで待ち受ける。Tailscale の `tailscale serve` が、
  自分の Tailscale ネットワーク（自分の PC とスマホだけ）からの https 接続を、この PC のサーバーへ中継する。
- Tailscale の名前（例: node.xxxx.ts.net）からの接続は、ペアリングした端末だけを通す。
  ペアリングは PC の画面に出した6桁の合言葉（10分・1回限り・5回まちがえたら無効）で行い、
  端末には推測できない合言葉（トークン）を HttpOnly の Cookie で渡す。サーバーにはそのハッシュだけを保存する。
- アカウントの仕組みは作らない。PC 本体からの操作だけで、オン・オフ・端末の解除ができる。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

COOKIE_NAME = "anotherme_device"
COOKIE_MAX_AGE = 400 * 24 * 3600  # ブラウザーが認める最長（約13か月）
PIN_SECONDS = 10 * 60
MAX_PIN_ATTEMPTS = 5

_DEFAULT_TAILSCALE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"


class RemoteError(Exception):
    def __init__(self, message: str, code: str = "remote_error", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class Device(BaseModel):
    id: str
    name: str
    token_hash: str
    created_at: str
    last_seen: str | None = None


class DeviceInfo(BaseModel):
    id: str
    name: str
    created_at: str
    last_seen: str | None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Pairing:
    pin: str
    expires: float
    attempts: int = 0


@dataclass
class RemoteAccess:
    """Tailscale の中継・ペアリングした端末・許可するホスト名を管理する。"""

    data_dir: Path
    port: int
    tailscale: Path | None = None
    # テストで Tailscale の代わりに使う（引数 → (終了コード, 出力)）
    runner: Any = None
    host: str | None = None
    _pairing: Pairing | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # ---------- Tailscale ----------

    def _exe(self) -> str | None:
        if self.tailscale is not None:
            return str(self.tailscale) if self.tailscale.exists() else None
        if _DEFAULT_TAILSCALE.exists():
            return str(_DEFAULT_TAILSCALE)
        return shutil.which("tailscale")

    def _run(self, *args: str) -> tuple[int, str]:
        if self.runner is not None:
            return self.runner(list(args))
        exe = self._exe()
        if exe is None:
            return 127, ""
        try:
            result = subprocess.run(
                [exe, *args], capture_output=True, timeout=20, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Tailscale command failed: %s", type(exc).__name__)
            return 1, ""
        return result.returncode, result.stdout

    def tailscale_status(self) -> dict[str, Any]:
        """Tailscale の状態（入っているか・ログインしているか・名前・https が使えるか・中継中か）。"""
        if self.runner is None and self._exe() is None:
            return {"installed": False, "logged_in": False, "dns_name": None, "https_ready": False, "serving": False}
        code, out = self._run("status", "--json")
        try:
            data = json.loads(out) if code == 0 else {}
        except ValueError:
            data = {}
        dns = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".") or None
        logged_in = data.get("BackendState") == "Running" and dns is not None
        https_ready = bool(dns and dns in (data.get("CertDomains") or []))
        code, out = self._run("serve", "status", "--json")
        serving = False
        if code == 0 and dns:
            try:
                serve = json.loads(out or "{}")
            except ValueError:
                serve = {}
            target = f"http://127.0.0.1:{self.port}"
            for web in (serve.get("Web") or {}).values():
                for handler in (web.get("Handlers") or {}).values():
                    if str(handler.get("Proxy", "")).rstrip("/") == target:
                        serving = True
        return {"installed": True, "logged_in": logged_in, "dns_name": dns, "https_ready": https_ready, "serving": serving}

    def enable(self) -> str:
        """Tailscale の https（443番）を、この PC のサーバーへ中継する。中継先のホスト名を返す。"""
        status = self.tailscale_status()
        if not status["installed"]:
            raise RemoteError("Tailscale が入っていません。先に Tailscale をインストールしてください。", "tailscale_missing", 409)
        if not status["logged_in"]:
            raise RemoteError("Tailscale にログインしていません。Tailscale を開いてログインしてください。", "tailscale_logged_out", 409)
        if not status["https_ready"]:
            raise RemoteError(
                "Tailscale の HTTPS が有効になっていません。管理画面の DNS ページで「Enable HTTPS」を押してください。",
                "tailscale_https_off", 409,
            )
        code, _ = self._run("serve", "--bg", "--https=443", f"http://127.0.0.1:{self.port}")
        if code != 0:
            raise RemoteError("Tailscale の中継を設定できませんでした。", "tailscale_serve_failed", 502)
        self.host = status["dns_name"]
        return str(self.host)

    def disable(self) -> None:
        self._run("serve", "--https=443", "off")
        self.host = None

    # ---------- ペアリング ----------

    @property
    def _devices_file(self) -> Path:
        return self.data_dir / "remote_devices.json"

    def _load(self) -> list[Device]:
        try:
            return [Device(**d) for d in json.loads(self._devices_file.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self, devices: list[Device]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._devices_file.with_suffix(".tmp")
        tmp.write_text(json.dumps([d.model_dump() for d in devices], ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._devices_file)

    def devices(self) -> list[DeviceInfo]:
        return [DeviceInfo(id=d.id, name=d.name, created_at=d.created_at, last_seen=d.last_seen) for d in self._load()]

    def start_pairing(self) -> tuple[str, float]:
        with self._lock:
            pin = f"{secrets.randbelow(1_000_000):06d}"
            self._pairing = Pairing(pin=pin, expires=time.time() + PIN_SECONDS)
            return pin, self._pairing.expires

    def pair(self, pin: str, name: str) -> str:
        """合言葉が合っていれば端末を登録し、端末に渡すトークンを返す。"""
        with self._lock:
            p = self._pairing
            if p is None or time.time() > p.expires:
                self._pairing = None
                raise RemoteError("合言葉の期限が切れています。PC で「スマホをつなぐ」を押し直してください。", "pin_expired", 403)
            if not secrets.compare_digest(pin.strip(), p.pin):
                p.attempts += 1
                if p.attempts >= MAX_PIN_ATTEMPTS:
                    self._pairing = None
                    raise RemoteError(
                        "合言葉を何度もまちがえたため、無効にしました。PC で「スマホをつなぐ」を押し直してください。", "pin_locked", 403
                    )
                raise RemoteError("合言葉がちがいます。PC の画面に出ている6桁の数字を入れてください。", "pin_wrong", 403)
            self._pairing = None
            token = secrets.token_urlsafe(32)
            device = Device(id=uuid.uuid4().hex, name=(name.strip() or "スマホ")[:40], token_hash=_hash(token), created_at=_now())
            self._save([*self._load(), device])
            return token

    def check(self, token: str | None) -> bool:
        """ペアリングした端末のトークンか。最後に使った時刻を（1時間に1回まで）記録する。"""
        if not token:
            return False
        digest = _hash(token)
        with self._lock:
            devices = self._load()
            for i, d in enumerate(devices):
                if secrets.compare_digest(d.token_hash, digest):
                    now = _now()
                    if d.last_seen is None or now[:13] != d.last_seen[:13]:
                        devices[i] = d.model_copy(update={"last_seen": now})
                        self._save(devices)
                    return True
        return False

    def remove(self, device_id: str) -> bool:
        with self._lock:
            devices = self._load()
            kept = [d for d in devices if d.id != device_id]
            if len(kept) == len(devices):
                return False
            self._save(kept)
            return True
