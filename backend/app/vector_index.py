"""ChromaDB による記憶のベクトル索引。

本文は保存せず、記憶ID（SQLite の主キー）とベクトルのみを保存する。
埋め込みモデルごとにコレクションを分け、モデル変更時は再インデックスする。
"""

from __future__ import annotations

import re
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings


def collection_name(model: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]", "-", model).strip("-._") or "default"
    return f"memories-{slug}"[:500]


class VectorIndex:
    def __init__(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        # 外部への利用状況送信（テレメトリ）を無効化する
        self._client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False)
        )

    def _collection(self, model: str):  # noqa: ANN202
        return self._client.get_or_create_collection(
            collection_name(model), embedding_function=None, configuration={"hnsw": {"space": "cosine"}}
        )

    def upsert(self, model: str, ids: list[str], embeddings: list[list[float]]) -> None:
        if ids:
            self._collection(model).upsert(ids=ids, embeddings=embeddings)

    def delete(self, ids: list[str]) -> None:
        """全モデルのコレクションから削除する（モデル切替前の索引も残さない）。"""
        if not ids:
            return
        for col in self._client.list_collections():
            if col.name.startswith("memories-"):
                self._client.get_collection(col.name, embedding_function=None).delete(ids=ids)

    def query(self, model: str, embedding: list[float], n_results: int) -> list[tuple[str, float]]:
        col = self._collection(model)
        if n_results <= 0 or col.count() == 0:
            return []
        result = col.query(query_embeddings=[embedding], n_results=n_results, include=["distances"])
        return list(zip(result["ids"][0], result["distances"][0], strict=True))

    def count(self, model: str) -> int:
        return self._collection(model).count()

    def ids(self, model: str) -> set[str]:
        return set(self._collection(model).get(include=[])["ids"])

    def drop_all(self) -> None:
        for col in self._client.list_collections():
            if col.name.startswith("memories-"):
                self._client.delete_collection(col.name)
