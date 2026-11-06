"""自分で用意した背景画像の保存。

画像は data/backgrounds/<id>.<拡張子> にサーバー側で決めた名前で保存し、一覧は index.json に持つ。
画像の中身（PNG / JPEG / WebP）を先頭のバイトで確かめ、それ以外は受け付けない。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

MAX_BACKGROUND_BYTES = 15 * 1024 * 1024

# home: 家（雨の日・朝晩にいる場所）/ indoor: 出かけ先（屋内）/ outdoor: 出かけ先（屋外。時間帯で明るさを変える）
BackgroundKind = Literal["home", "indoor", "outdoor"]

_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


class BackgroundError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class Background(BaseModel):
    id: str
    name: str
    kind: BackgroundKind
    ext: str
    size: int


def detect_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise BackgroundError("PNG・JPEG・WebP の画像を選んでください。")


class BackgroundStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()

    @property
    def _index(self) -> Path:
        return self.directory / "index.json"

    def list(self) -> list[Background]:
        try:
            items = json.loads(self._index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        result = []
        for item in items:
            try:
                bg = Background(**item)
            except ValueError:
                continue
            if self.path_for(bg).is_file():
                result.append(bg)
        return result

    def get(self, background_id: str) -> Background | None:
        return next((b for b in self.list() if b.id == background_id), None)

    def path_for(self, bg: Background) -> Path:
        return self.directory / f"{uuid.UUID(hex=bg.id).hex}.{bg.ext}"

    @staticmethod
    def media_type(bg: Background) -> str:
        return _TYPES[bg.ext]

    def _save_index(self, items: list[Background]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self._index.with_suffix(".tmp")
        tmp.write_text(json.dumps([b.model_dump() for b in items], ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._index)

    def add(self, data: bytes, name: str, kind: BackgroundKind) -> Background:
        if len(data) > MAX_BACKGROUND_BYTES:
            raise BackgroundError("画像が大きすぎます（15MBまで）。", 413)
        ext = detect_type(data)
        bg = Background(id=uuid.uuid4().hex, name=(name.strip() or "背景")[:40], kind=kind, ext=ext, size=len(data))
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path_for(bg)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
            self._save_index([*self.list(), bg])
        return bg

    def update(self, background_id: str, name: str | None, kind: BackgroundKind | None) -> Background | None:
        with self._lock:
            items = self.list()
            for i, bg in enumerate(items):
                if bg.id == background_id:
                    changes: dict = {}
                    if name is not None:
                        changes["name"] = name.strip()[:40] or bg.name
                    if kind is not None:
                        changes["kind"] = kind
                    items[i] = bg.model_copy(update=changes)
                    self._save_index(items)
                    return items[i]
        return None

    def delete(self, background_id: str) -> bool:
        with self._lock:
            items = self.list()
            target = next((b for b in items if b.id == background_id), None)
            if target is None:
                return False
            self._save_index([b for b in items if b.id != background_id])
            self.path_for(target).unlink(missing_ok=True)
            return True
