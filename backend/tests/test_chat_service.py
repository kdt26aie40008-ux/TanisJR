from __future__ import annotations

from app.schemas import AppSettings, ChatMessage
from app.services.chat import ThinkTagFilter, build_attempts, trim_history
from app.services.persona import build_system_prompt


def run_filter(chunks: list[str]) -> list[tuple[str, str]]:
    f = ThinkTagFilter()
    out = [item for c in chunks for item in f.feed(c)] + f.flush()
    merged: list[tuple[str, str]] = []
    for kind, text in out:
        if merged and merged[-1][0] == kind:
            merged[-1] = (kind, merged[-1][1] + text)
        else:
            merged.append((kind, text))
    return merged


def test_think_filter_plain_text() -> None:
    assert run_filter(["こんに", "ちは"]) == [("token", "こんにちは")]


def test_think_filter_splits_tags_across_chunks() -> None:
    assert run_filter(["<thi", "nk>考え中</th", "ink>答え"]) == [("thinking", "考え中"), ("token", "答え")]


def test_think_filter_keeps_lone_angle_bracket() -> None:
    assert run_filter(["a < b", " <t"]) == [("token", "a < b <t")]


def test_attempts_order() -> None:
    settings = AppSettings(model="qwen3:8b", fallback_model="qwen3:4b", num_ctx=4096)
    attempts = build_attempts(settings)
    assert [a.model for a in attempts] == ["qwen3:8b", "qwen3:8b", "qwen3:8b", "qwen3:4b"]
    assert attempts[0].notice == ""
    assert attempts[1].options["num_ctx"] == 2048
    assert attempts[2].options["num_gpu"] == 0


def test_attempts_skip_ctx_reduction_when_already_small() -> None:
    attempts = build_attempts(AppSettings(num_ctx=2048))
    assert len(attempts) == 2
    assert attempts[1].options["num_gpu"] == 0


def test_trim_history_keeps_latest_user_message() -> None:
    messages = [
        ChatMessage(role="user", content="古い" * 2000),
        ChatMessage(role="assistant", content="返答" * 2000),
        ChatMessage(role="user", content="最新"),
    ]
    trimmed = trim_history(messages, "system", 4096)
    assert [m.content for m in trimmed] == ["最新"]


def test_trim_history_keeps_all_when_fits() -> None:
    messages = [ChatMessage(role="user", content="a"), ChatMessage(role="assistant", content="b"), ChatMessage(role="user", content="c")]
    assert trim_history(messages, "system", 4096) == messages


def test_system_prompt_without_profile_forbids_guessing() -> None:
    prompt = build_system_prompt("タニス", [])
    assert "タニス" in prompt
    assert "推測で作らない" in prompt
    assert "まだ情報はありません" in prompt
    assert "関連する記憶" not in prompt


def test_system_prompt_has_date_and_no_realtime_rule() -> None:
    from datetime import date

    prompt = build_system_prompt("タニス", [], today=date(2026, 11, 2))
    assert "2026年11月2日（月）" in prompt
    assert "でっち上げない" in prompt
    assert "ユーザー本人ではなく" in prompt
