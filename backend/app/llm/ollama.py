"""Ollama HTTP API クライアント（ストリーミング・エラー分類）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

_OOM_MARKERS = (
    "out of memory",
    "cudamalloc",
    "requires more system memory",
    "insufficient memory",
    "not enough memory",
)


class OllamaError(Exception):
    """ユーザーに表示できる日本語メッセージを持つ例外。"""

    code = "ollama_error"

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class OllamaUnavailable(OllamaError):
    code = "ollama_unavailable"


class ModelNotFound(OllamaError):
    code = "model_not_found"


class OutOfMemory(OllamaError):
    code = "out_of_memory"


def classify_error(status: int, message: str, model: str = "") -> OllamaError:
    lowered = message.lower()
    if any(m in lowered for m in _OOM_MARKERS):
        return OutOfMemory("GPUまたはメモリが不足しているため、モデルを実行できませんでした。", message)
    if status == 404 or ("model" in lowered and "not found" in lowered):
        return ModelNotFound(
            f"モデル「{model}」がインストールされていません。設定画面からダウンロードしてください。", message
        )
    return OllamaError("AIモデルの実行中にエラーが発生しました。", message)


class OllamaClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            # 初回はモデル読み込みに時間がかかるため読み取りタイムアウトは長めにする
            timeout=httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def version(self) -> str:
        data = await self._get_json("/api/version")
        return str(data.get("version", ""))

    async def list_models(self) -> list[dict[str, Any]]:
        data = await self._get_json("/api/tags")
        return list(data.get("models", []))

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any],
        think: bool,
    ) -> AsyncIterator[dict[str, Any]]:
        """Ollama /api/chat の NDJSON チャンクを順に返す。"""
        body = {"model": model, "messages": messages, "options": options, "think": think, "stream": True}
        async for chunk in self._stream("POST", "/api/chat", body, model):
            yield chunk

    async def chat_once(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any],
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """ストリーミングせずに応答本文を返す（記憶抽出など内部処理用）。"""
        body: dict[str, Any] = {"model": model, "messages": messages, "options": options, "think": False, "stream": False}
        if response_format is not None:
            body["format"] = response_format
        data = await self._post_json("/api/chat", body, model)
        return str((data.get("message") or {}).get("content", ""))

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        data = await self._post_json("/api/embed", {"model": model, "input": inputs}, model)
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(inputs):
            raise OllamaError("埋め込みの計算結果が不正です。", "invalid embed response")
        return embeddings

    async def loaded_models(self) -> list[str]:
        """GPU/メモリに読み込まれているモデル名（/api/ps）。"""
        data = await self._get_json("/api/ps")
        return [str(m.get("name")) for m in data.get("models", []) if m.get("name")]

    async def unload(self, model: str) -> None:
        """モデルをすぐにメモリから解放する（学習のために GPU メモリを空ける）。"""
        await self._post_json("/api/generate", {"model": model, "keep_alive": 0}, model)

    async def delete_model(self, model: str) -> None:
        try:
            response = await self._client.request("DELETE", "/api/delete", json={"model": model})
        except httpx.TransportError as exc:
            raise _unavailable(exc) from exc
        if response.status_code not in (200, 404):
            raise classify_error(response.status_code, _error_text(response.text), model)

    async def pull(self, model: str) -> AsyncIterator[dict[str, Any]]:
        async for chunk in self._stream("POST", "/api/pull", {"model": model, "stream": True}, model):
            yield chunk

    async def _get_json(self, path: str) -> dict[str, Any]:
        try:
            response = await self._client.get(path)
        except httpx.TransportError as exc:
            raise _unavailable(exc) from exc
        if response.status_code != 200:
            raise classify_error(response.status_code, _error_text(response.text))
        return response.json()

    async def _post_json(self, path: str, body: dict, model: str) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body)
        except httpx.TransportError as exc:
            raise _unavailable(exc) from exc
        if response.status_code != 200:
            raise classify_error(response.status_code, _error_text(response.text), model)
        return response.json()

    async def _stream(self, method: str, path: str, body: dict, model: str) -> AsyncIterator[dict[str, Any]]:
        try:
            async with self._client.stream(method, path, json=body) as response:
                if response.status_code != 200:
                    text = (await response.aread()).decode("utf-8", errors="replace")
                    raise classify_error(response.status_code, _error_text(text), model)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise classify_error(500, str(chunk["error"]), model)
                    yield chunk
        except httpx.TransportError as exc:
            raise _unavailable(exc) from exc


def _unavailable(exc: Exception) -> OllamaUnavailable:
    return OllamaUnavailable(
        "Ollama に接続できません。Ollama が起動しているか確認してください。", type(exc).__name__
    )


def _error_text(text: str) -> str:
    try:
        return str(json.loads(text).get("error", text))
    except (ValueError, AttributeError):
        return text
