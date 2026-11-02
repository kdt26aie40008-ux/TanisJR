"""ダウンロード可能なモデルの一覧。

ユーザーの確認なしに未知のモデルを取得しないよう、DL はこの一覧にあるモデルに限定する。
サイズは Ollama ライブラリ掲載値の目安（実際のサイズは変わる場合がある）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class CatalogModel:
    name: str
    size_gb: float
    description: str
    kind: Literal["chat", "embedding"] = "chat"
    recommended: bool = False


MODEL_CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel("qwen3:8b", 5.2, "標準モデル（Q4_K_M）。RTX 5060 8GB で全層GPU実行可能", recommended=True),
    CatalogModel("qwen3:4b", 2.5, "軽量モデル。GPUメモリ不足時の代替向け"),
    CatalogModel("qwen3:1.7b", 1.4, "最軽量モデル。CPUのみでも比較的軽快"),
    CatalogModel("qwen3-embedding:0.6b", 0.64, "記憶検索用（埋め込み）。多言語・日本語対応", kind="embedding", recommended=True),
    CatalogModel("bge-m3", 1.2, "記憶検索用（埋め込み）。多言語対応の定番モデル", kind="embedding"),
)


def find(name: str) -> CatalogModel | None:
    return next((m for m in MODEL_CATALOG if m.name == name), None)


def as_dicts() -> list[dict]:
    return [asdict(m) for m in MODEL_CATALOG]
