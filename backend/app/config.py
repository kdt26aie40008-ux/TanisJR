"""実行時設定。値は環境変数から読み込み、外部通信先はローカルホストに限定する。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]

LOCAL_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    data_dir: Path
    ollama_url: str
    port: int
    frontend_dist: Path
    aivis_url: str = "http://127.0.0.1:10101"
    models_dir: Path = REPO_ROOT / "models"
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    # 状態変更リクエストを許可するオリジン（本番 + Vite 開発サーバー）
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "twin.db"


def validate_local_url(url: str) -> str:
    """ローカルホスト以外の URL を拒否する（不要な外部通信の防止）。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTNAMES:
        raise ConfigError(f"ローカルホスト以外の URL は使用できません: {url}")
    return url.rstrip("/")


def load_config() -> Config:
    port = int(os.environ.get("TWIN_PORT", "8765"))
    data_dir = Path(os.environ.get("TWIN_DATA_DIR", REPO_ROOT / "data")).resolve()
    ollama_url = validate_local_url(os.environ.get("TWIN_OLLAMA_URL", "http://127.0.0.1:11434"))
    origins = tuple(
        f"http://{host}:{p}" for host in ("127.0.0.1", "localhost") for p in (port, 5173)
    )
    return Config(
        data_dir=data_dir,
        ollama_url=ollama_url,
        port=port,
        frontend_dist=REPO_ROOT / "frontend" / "dist",
        aivis_url=validate_local_url(os.environ.get("TWIN_AIVIS_URL", "http://127.0.0.1:10101")),
        models_dir=Path(os.environ.get("TWIN_MODELS_DIR", REPO_ROOT / "models")).resolve(),
        allowed_origins=origins,
    )
