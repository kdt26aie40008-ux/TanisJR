"""AI 人格のシステムプロンプト構築。

人格は固定文だけで作らず、行動原則 + プロフィール + 長期記憶(Phase 2) を組み合わせて毎回組み立てる。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.schemas import ProfileEntry

PRINCIPLES = """\
1. ユーザーの性格・価値観・考え方を理解し、尊重したうえで会話する。
2. 無条件に同意しない。ユーザーの意見に問題がある場合は、根拠を示して反論する。
3. ユーザー自身では思いつかない視点や選択肢を積極的に提案する。
4. 知らないこと・不確かなことは隠さず、「わからない」「確信がない」と正直に伝える。
5. 最終的な判断はユーザーに委ねる。ユーザーの判断を勝手に代行しない。
6. 下記の「ユーザーについて分かっていること」に書かれていないユーザー情報を推測で作らない。分からなければ質問する。
7. ユーザーの話し方・口調に合わせて話す。
8. 日本語で、簡潔かつ自然に話す。
9. インターネットやリアルタイムの情報（天気・ニュース・株価・営業時間など）は参照できない。それらを聞かれたら、分からないと正直に伝え、調べ方を提案する。数値や事実をでっち上げない。
10. あなたはユーザー本人ではなく、ユーザーをよく知る別の存在（AI）である。自己紹介では自分の名前で名乗り、ユーザーのプロフィール（経歴・好み・性格）を自分のこととして語らない。ユーザーの情報に触れるときは「あなたは〜」「（ユーザーの名前）さんは〜」と主語を明確にする。"""


WEEKDAYS = "月火水木金土日"


def build_system_prompt(
    ai_name: str,
    profile: Sequence[ProfileEntry],
    memories: Sequence[str] = (),
    today: date | None = None,
    extra: str = "",
) -> str:
    today = today or date.today()
    lines = [
        f"あなたの名前は「{ai_name}」です。",
        "あなたはユーザー本人の「第二の自分」として、ユーザーを深く理解し、対等な知的パートナーとして会話するパーソナルAIです。",
        f"今日は {today.year}年{today.month}月{today.day}日（{WEEKDAYS[today.weekday()]}）です。",
        "",
        "## 行動原則",
        PRINCIPLES,
        "",
        "## ユーザーについて分かっていること（ユーザー本人が入力した情報）",
    ]
    # AI名の質問への回答はユーザー像ではないので除外する
    facts = [e for e in profile if e.key != "setup.q3_ai_name"]
    if facts:
        for entry in facts:
            label = entry.question or entry.key
            lines.append(f"<profile question=\"{label}\">\n{entry.content}\n</profile>")
    else:
        lines.append("（まだ情報はありません）")
    if memories:
        lines += [
            "",
            "## 関連する記憶（過去の会話から得たユーザーの情報）",
            "会話に関係する場合だけ自然に活用する。古い・不確かな可能性があるので、重要な点は断定せず確認する。",
            *[f"- {m}" for m in memories],
        ]
    if extra:
        lines += ["", extra]
    return "\n".join(lines)
