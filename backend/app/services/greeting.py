"""返事の頭の、いらないあいさつを取り除く。

qwen3:8b は「あいさつされていなければ、あいさつしない」と指示しても、半分ほどの返事を
「こんばんは。」から始めた（実機で確認）。そこで、ユーザーがあいさつも自己紹介の依頼もしていないときは、
返事の頭のあいさつだけをプログラムで取り除く。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from app.services.persona import is_self_intro_request

# ユーザーの発言がこれを含むなら、あいさつを返してよい
_USER_GREETS = re.compile(
    r"おはよ|こんにち[はわ]|こんばん[はわ]|やあ|はじめまして|初めまして|自己紹介|よろしく|ただいま|おっす|ハロー|もしもし"
)
# 返事の頭のあいさつ（「今夜はこんばんは。」のような崩れた形も含む）
_LEADING = re.compile(
    r"^\s*(?:今夜は|今日は)?(?:おはようございます|おはよう|こんにちは|こんばんは)(?:、[^、。！!？?\s]{1,8}[、。！!])?[、。！!～〜\s]*"
    # 呼びかけ（「、ケン。」）は、すぐ後に句読点があるときだけ取る（「こんばんは、最近どう？」の本題は残す）
)
# 判定に使う文字数（これだけたまってから、頭のあいさつを調べる）
_DECIDE_AT = 24


def user_greeted(text: str) -> bool:
    """ユーザーがあいさつしたか、AI に名乗るよう求めたか（どちらもあいさつを返してよい）。"""
    return bool(_USER_GREETS.search(text)) or is_self_intro_request(text)


def trim_leading_greeting(text: str) -> str:
    trimmed = _LEADING.sub("", text, count=1)
    # 全部があいさつだった場合は、そのまま返す（返事が空にならないように）
    return trimmed if trimmed.strip() else text


async def without_unasked_greeting(
    events: AsyncIterator[dict[str, Any]], user_text: str
) -> AsyncIterator[dict[str, Any]]:
    """token イベントの頭のあいさつを取り除く。ユーザーがあいさつしたときは何もしない。"""
    if user_greeted(user_text):
        async for event in events:
            yield event
        return
    buffer = ""
    decided = False
    async for event in events:
        if event["type"] == "token" and not decided:
            buffer += event["content"]
            if len(buffer) < _DECIDE_AT:
                continue
            decided = True
            yield {**event, "content": trim_leading_greeting(buffer)}
            continue
        if not decided and buffer:
            # 返事が短く、判定する前に終わった・別のイベントが来た
            decided = True
            yield {"type": "token", "content": trim_leading_greeting(buffer)}
        yield event
