import asyncio

import pytest

from app.services.greeting import trim_leading_greeting, user_greeted, without_unasked_greeting


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("こんばんは。勉強法の話なら、ペースが大事やで。", "勉強法の話なら、ペースが大事やで。"),
        ("こんばんは、ケン。最近どう？", "最近どう？"),
        ("こんばんは、ケンさん！徹夜はあかんで。", "徹夜はあかんで。"),
        ("今夜はこんばんは。勉強法の話やな。", "勉強法の話やな。"),
        ("おはようございます。今日も頑張ろう。", "今日も頑張ろう。"),
        # 呼びかけでない続きは残す
        ("こんばんは、なんかやる気出ないの？", "なんかやる気出ないの？"),
        # あいさつで始まっていなければ何もしない
        ("徹夜は体に悪いで。", "徹夜は体に悪いで。"),
        ("ケンさん、こんばんは。", "ケンさん、こんばんは。"),
        # 全部があいさつなら、空にしない
        ("こんばんは。", "こんばんは。"),
    ],
)
def test_trim_leading_greeting(text: str, expected: str) -> None:
    assert trim_leading_greeting(text) == expected


def test_user_greeted() -> None:
    assert user_greeted("こんばんは")
    assert user_greeted("自己紹介して")
    assert user_greeted("やあ、元気？")
    assert user_greeted("あなたは誰？")
    assert not user_greeted("おすすめの勉強法ある？")


async def _events(tokens: list[str]):
    for t in tokens:
        yield {"type": "token", "content": t}
    yield {"type": "done", "model": "m"}


def _run(tokens: list[str], user_text: str) -> list[dict]:
    async def collect() -> list[dict]:
        return [e async for e in without_unasked_greeting(_events(tokens), user_text)]

    return asyncio.run(collect())


def _text(events: list[dict]) -> str:
    return "".join(e["content"] for e in events if e["type"] == "token")


def test_stream_removes_unasked_greeting_across_tokens() -> None:
    tokens = ["こん", "ばんは", "。", "勉強法", "の話なら、", "自分に合った", "ペースが", "大事やで。"]
    events = _run(tokens, "おすすめの勉強法ある？")
    assert _text(events) == "勉強法の話なら、自分に合ったペースが大事やで。"
    assert events[-1]["type"] == "done"


def test_stream_keeps_greeting_when_user_greeted() -> None:
    tokens = ["こんばんは。", "今何してた？"]
    assert _text(_run(tokens, "こんばんは")) == "こんばんは。今何してた？"


def test_stream_short_reply_is_flushed_before_done() -> None:
    events = _run(["こんばんは。", "どうしたん？"], "ねえ")
    assert _text(events) == "どうしたん？"
    assert [e["type"] for e in events] == ["token", "done"]
