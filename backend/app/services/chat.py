"""チャット推論。GPU メモリ不足時のフォールバックと、思考タグの分離を行う。

会話本文はここで一時的に処理するだけで、保存もログ出力もしない。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from app.llm.ollama import OllamaClient, OllamaError, OutOfMemory
from app.schemas import AppSettings, ChatMessage

logger = logging.getLogger(__name__)

REDUCED_NUM_CTX = 2048
# 応答生成のために確保する文字数（日本語はおおむね 1文字≒1トークン）
RESPONSE_RESERVE = 1024


@dataclass(frozen=True)
class Attempt:
    model: str
    options: dict[str, Any]
    notice: str = ""


def build_attempts(settings: AppSettings) -> list[Attempt]:
    base = {"temperature": settings.temperature, "num_ctx": settings.num_ctx}
    attempts = [Attempt(settings.model, base)]
    reduced = {**base, "num_ctx": min(settings.num_ctx, REDUCED_NUM_CTX)}
    if reduced["num_ctx"] < settings.num_ctx:
        attempts.append(
            Attempt(settings.model, reduced, "GPUメモリ不足のため、会話の記憶範囲（コンテキスト長）を縮小して再試行しています。")
        )
    attempts.append(
        Attempt(settings.model, {**reduced, "num_gpu": 0}, "GPUメモリ不足のため、CPUで実行しています（応答が遅くなります）。")
    )
    if settings.fallback_model and settings.fallback_model != settings.model:
        attempts.append(
            Attempt(settings.fallback_model, base, f"GPUメモリ不足のため、代替モデル「{settings.fallback_model}」で応答しています。")
        )
    return attempts


def trim_history(messages: Sequence[ChatMessage], system_prompt: str, num_ctx: int) -> list[ChatMessage]:
    """コンテキスト長に収まるよう古い発言から削る。最後のユーザー発言は必ず残す。"""
    budget = max(num_ctx - len(system_prompt) - RESPONSE_RESERVE, 0)
    kept: list[ChatMessage] = []
    used = 0
    for message in reversed(messages):
        cost = len(message.content)
        if kept and used + cost > budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    # 先頭がアシスタント発言だと文脈が不自然になるため落とす
    while len(kept) > 1 and kept[0].role == "assistant":
        kept.pop(0)
    return kept


class ThinkTagFilter:
    """本文に混入した <think>...</think> を思考として分離する（チャンク境界をまたいでも動作する）。"""

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, text: str) -> list[tuple[str, str]]:
        self._buf += text
        out: list[tuple[str, str]] = []
        while self._buf:
            kind = "thinking" if self._in_think else "token"
            tag = self.CLOSE if self._in_think else self.OPEN
            idx = self._buf.find(tag)
            if idx >= 0:
                if idx:
                    out.append((kind, self._buf[:idx]))
                self._buf = self._buf[idx + len(tag):]
                self._in_think = not self._in_think
                continue
            keep = _partial_suffix_len(self._buf, tag)
            emit = self._buf[: len(self._buf) - keep]
            if emit:
                out.append((kind, emit))
            self._buf = self._buf[len(self._buf) - keep:]
            break
        return out

    def flush(self) -> list[tuple[str, str]]:
        rest, self._buf = self._buf, ""
        return [("thinking" if self._in_think else "token", rest)] if rest else []


def _partial_suffix_len(text: str, tag: str) -> int:
    for n in range(min(len(text), len(tag) - 1), 0, -1):
        if text.endswith(tag[:n]):
            return n
    return 0


@dataclass
class _Emitter:
    started: bool = False
    leading: bool = True

    def push(self, kind: str, text: str) -> dict[str, Any] | None:
        if kind == "token" and self.leading:
            # 思考タグ直後の空行を除く
            text = text.lstrip()
            if not text:
                return None
            self.leading = False
        self.started = True
        return {"type": kind, "content": text}


async def stream_chat(
    client: OllamaClient,
    settings: AppSettings,
    system_prompt: str,
    history: Sequence[ChatMessage],
) -> AsyncIterator[dict[str, Any]]:
    """SSE で送るイベント (token / thinking / notice / error / done) を順に返す。"""
    attempts = build_attempts(settings)
    for index, attempt in enumerate(attempts):
        if attempt.notice:
            yield {"type": "notice", "message": attempt.notice}
        trimmed = trim_history(history, system_prompt, int(attempt.options["num_ctx"]))
        messages = [{"role": "system", "content": system_prompt}] + [m.model_dump() for m in trimmed]
        emitter = _Emitter()
        tag_filter = ThinkTagFilter()
        try:
            async for chunk in client.chat_stream(attempt.model, messages, attempt.options, settings.think):
                message = chunk.get("message") or {}
                if message.get("thinking"):
                    event = emitter.push("thinking", message["thinking"])
                    if event:
                        yield event
                for kind, text in tag_filter.feed(message.get("content") or ""):
                    event = emitter.push(kind, text)
                    if event:
                        yield event
                if chunk.get("done"):
                    break
            for kind, text in tag_filter.flush():
                event = emitter.push(kind, text)
                if event:
                    yield event
            yield {"type": "done", "model": attempt.model}
            return
        except OutOfMemory as exc:
            logger.warning("OOM on attempt %d (model=%s): %s", index, attempt.model, exc.detail)
            if emitter.started or index == len(attempts) - 1:
                yield {"type": "error", "code": exc.code, "message": exc.message}
                return
        except OllamaError as exc:
            logger.warning("Ollama error (%s): %s", exc.code, exc.detail)
            yield {"type": "error", "code": exc.code, "message": exc.message}
            return
