"""保存を許可された会話から、ユーザーについての記憶候補を LLM で抽出する。"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.llm.ollama import OllamaClient

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 5
MAX_CANDIDATE_LEN = 300

CATEGORIES = ["preference", "habit", "fact", "personal", "personality", "values", "other"]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 10},
                    "sensitive": {"type": "boolean"},
                },
                "required": ["content", "category", "importance", "sensitive"],
            },
        }
    },
    "required": ["memories"],
}

SYSTEM_PROMPT = """\
あなたは、ユーザーとAIの会話から「ユーザー自身についての長期的に役立つ情報」を抽出する担当です。

## ルール
- 抽出してよいのは【ユーザーの発言】の中でユーザー本人が明言したことだけ。推測・一般化しない。
- 【直前のAIの発言】は文脈の理解にだけ使い、そこから情報を抽出しない。
- 一時的な内容（今日の予定だけの話、単発の質問、雑談のあいさつ）は抽出しない。
- 各項目は「ユーザーは〜」で始まる、短く具体的な日本語の1文にする。
- 該当する情報がなければ memories を空配列にする。無理に作らない。
- 最大5件。

## category
- preference: 好み（食べ物・飲み物・趣味・好きなもの/嫌いなもの）
- habit: 日々の習慣・話し方・考え方の傾向
- fact: 本人に関する一般的な事実（ペット、使っている道具、学んでいる分野など）
- personal: 個人情報（氏名・住んでいる地域・出身地・連絡先・年齢・勤務先・学校・健康・家族・恋人・収入など）
- personality: 性格
- values: 価値観・信念・人生観
- other: その他

住んでいる地域・勤務先・学校・年齢は fact ではなく必ず personal にする。

## importance（1〜10）
今後の会話でユーザーを理解するうえでの有用度。

## sensitive
次のいずれかなら true:
- 個人を特定しうる情報（住んでいる地域、勤務先、学校、年齢、氏名、連絡先）
- 本人への影響が大きい情報（健康、家族、恋愛、お金、人間関係の悩み、宗教、政治）
日常の好みや習慣（飲み物の好み、趣味など）は false。

## 例
ユーザーの発言「毎朝コーヒーを飲むのが習慣。大阪に住んでる。」
→ {"memories": [
  {"content": "ユーザーは毎朝コーヒーを飲むのが習慣", "category": "habit", "importance": 4, "sensitive": false},
  {"content": "ユーザーは大阪に住んでいる", "category": "personal", "importance": 6, "sensitive": true}
]}"""


class Candidate(BaseModel):
    content: str = Field(min_length=1)
    category: Literal["preference", "habit", "fact", "personal", "personality", "values", "other"]
    importance: int = Field(ge=1, le=10)
    sensitive: bool


class _Result(BaseModel):
    memories: list[Candidate]


def ai_name_rule(ai_names: Sequence[str]) -> str:
    """AI の名前（呼びかけ）を、ユーザーの知り合いとして記憶しないための説明。"""
    names = "・".join(f"「{n}」" for n in ai_names if n.strip())
    if not names:
        return ""
    return (
        "\n\n## AI の名前\n"
        f"{names}はこの会話の AI の名前。ユーザーがそう呼びかけたり、その名前に向けて話したりしているのは AI への呼びかけ。"
        "その名前を、ユーザーの知り合い・家族・友人など別の人として記憶しない。呼びかけ自体は抽出しない。"
    )


def build_messages(
    user_text: str, previous_assistant: str | None, ai_names: Sequence[str] = ()
) -> list[dict[str, str]]:
    parts = []
    if previous_assistant:
        parts.append(f"【直前のAIの発言】（参考のみ。ここからは抽出しない）\n<ai>\n{previous_assistant}\n</ai>")
    parts.append(f"【ユーザーの発言】（ここから抽出する）\n<user>\n{user_text}\n</user>")
    return [
        {"role": "system", "content": SYSTEM_PROMPT + ai_name_rule(ai_names)},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def parse_candidates(raw: str) -> list[Candidate]:
    try:
        result = _Result.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        logger.warning("Memory extraction returned an invalid response")
        return []
    candidates = []
    for c in result.memories[:MAX_CANDIDATES]:
        content = " ".join(c.content.split())[:MAX_CANDIDATE_LEN]
        if content:
            candidates.append(c.model_copy(update={"content": content}))
    return candidates


async def extract_candidates(
    client: OllamaClient,
    model: str,
    user_text: str,
    previous_assistant: str | None,
    ai_names: Sequence[str] = (),
) -> list[Candidate]:
    raw = await client.chat_once(
        model,
        build_messages(user_text, previous_assistant, ai_names),
        {"temperature": 0.0, "num_ctx": 4096},
        response_format=RESPONSE_SCHEMA,
    )
    return parse_candidates(raw)
