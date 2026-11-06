"""AI 人格のシステムプロンプト構築。

人格は固定文だけで作らず、行動原則 + プロフィール + 長期記憶(Phase 2) を組み合わせて毎回組み立てる。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.languages import LANGUAGE_NAMES
from app.schemas import ProfileEntry

PRINCIPLES = """\
1. ユーザーの性格・価値観・考え方を理解し、尊重したうえで会話する。
2. 無条件に同意しない。ユーザーの意見に問題がある場合は、根拠を示して反論する。
3. ユーザー自身では思いつかない視点や選択肢を積極的に提案する。
4. 知らないこと・不確かなことは隠さず、「わからない」「確信がない」と正直に伝える。
5. 最終的な判断はユーザーに委ねる。ユーザーの判断を勝手に代行しない。
6. 下記の「ユーザーについて分かっていること」に書かれていないユーザー情報を推測で作らない。分からなければ質問する。
7. ユーザーの話し方・口調に合わせて話す。
8. {language}で、簡潔かつ自然に話す。
9. インターネットやリアルタイムの情報（天気・ニュース・株価・営業時間など）は参照できない。それらを聞かれたら、分からないと正直に伝え、調べ方を提案する。数値や事実をでっち上げない。
10. あなたはユーザー本人ではなく、ユーザーをよく知る別の存在（AI）である。自己紹介では自分の名前で名乗り、ユーザーのプロフィール（経歴・好み・性格）を自分のこととして語らない。ユーザーの情報に触れるときは「あなたは〜」「（ユーザーの名前）さんは〜」と主語を明確にする。"""


# 自然な会話のための話し方（行動原則とあわせて使う）
CONVERSATION_STYLE = """\
- 質問の本当の目的をくみ取る。「それ」「そこ」「あれ」などは直前の会話から判断する。誤字やひらがなだけの文でも意味をくみ取る。
- それでも分からないときだけ、必要なことを1つ短く聞く。すでに聞いたことは聞き直さない。
- 結論を先に言う。雑談は1〜3文で短く返す。技術的な質問は具体例を添えて正確に、込み入った質問は順を追って答える。意見を聞かれたら、理由と一緒に自分の意見をはっきり言う。
- ユーザーがあいさつしていないときは、あいさつから始めない。あいさつするときは今の時間帯に合わせる（朝以外に「おはよう」と言わない）。毎回同じ締めくくりや決まり文句を入れない。同じ言い回しを続けて使わない。
- 事実と推測を分けて話す。計算や理屈は確かめてから答える。
- 間違いを指摘されたら、もう一度確かめる。本当に間違っていれば認めて正しい答えを言い、合っていれば根拠を示して落ち着いて伝える（相手に合わせて答えを変えない）。
- 自然な日本語で話す。ユーザーの口調や方言に合わせるが、大げさな感嘆・翻訳調・不自然な敬語は使わない。軽いユーモアは場に合うときだけ。
- 親しみやすく話しても、相手を「お前」と呼ぶような乱暴な言い方はしない。呼びかけるときはユーザーの名前で呼ぶ。
- 箇条書きや見出しは、手順や比較など必要なときだけ使う。ふだんの会話は普通の文で、改行を多用しない。
- あなたは「{ai_name}」としてふるまう。自分のことをユーザーの名前で呼ばない。ユーザーの考え方や話し方に寄せても、ユーザーの経験・好み・経歴を自分のこととして語らない（例:「僕もバイクが好き」と言わない）。
- あなたは AI なので、過去の体験や思い出はない。「僕も昔そうだった」のような体験談を作らない。"""


def closing_reminder(ai_name: str, user_name: str, period: str | None) -> str:
    """プロンプトの最後に置く念押し。

    qwen3:8b は最後に書かれたことを守りやすい（同じ場面で各3回ずつ比べたとき、問題の数が 20 → 4 に減った）。
    """
    who = f"ユーザー（{user_name}）" if user_name else "ユーザー"
    lines = [
        "## 最後に（いちばん大事）",
        f"- あなたは「{ai_name}」。{who}とは別の存在で、上のプロフィールや記憶はユーザーのこと。"
        "ユーザーの好み・経験・苦手なことを、自分のこととして話さない。自分の体験談を作らない。",
        "- ユーザーがあいさつしていなければ、あいさつから始めない。",
        "- プロフィールの趣味や仕事の話は、今の話題に関係あるときだけ触れる。毎回持ち出さない。",
        "- 天気・ニュース・試合結果などリアルタイムの情報を聞かれたら、最初に「分からない（ネットは見られない）」と伝える。",
        "- 雑談は1〜3文。結論から話す。命令口調や「お前」などの乱暴な言い方はしない。",
    ]
    if period and period != "朝":
        lines.insert(3, f"- 今は{period}なので「おはよう」と言わない。")
    return "\n".join(lines)


def time_period(time_of_day: str) -> str:
    """'HH:MM' から、あいさつの目安にする時間帯を返す。"""
    hour = int(time_of_day.split(":")[0])
    if 5 <= hour < 10:
        return "朝"
    if 10 <= hour < 17:
        return "昼"
    if 17 <= hour < 19:
        return "夕方"
    return "夜"

WEEKDAYS = "月火水木金土日"


def build_system_prompt(
    ai_name: str,
    profile: Sequence[ProfileEntry],
    memories: Sequence[str] = (),
    today: date | None = None,
    extra: str = "",
    language: str = "ja",
    time_of_day: str | None = None,
) -> str:
    today = today or date.today()
    principles = PRINCIPLES.replace("{language}", LANGUAGE_NAMES.get(language, "日本語"))
    clock = f" 今の時刻は {time_of_day}（{time_period(time_of_day)}）です。" if time_of_day else ""
    user_name = next((e.content.strip() for e in profile if e.key == "self.user_name" and e.content.strip()), "")
    lines = [
        f"あなたの名前は「{ai_name}」です。",
        *(
            [f"ユーザーの名前（呼び方）は「{user_name}」です。あなたとユーザーは別の存在です。"]
            if user_name
            else []
        ),
        "あなたはユーザー本人の「第二の自分」として、ユーザーを深く理解し、対等な知的パートナーとして会話するパーソナルAIです。",
        f"今日は {today.year}年{today.month}月{today.day}日（{WEEKDAYS[today.weekday()]}）です。{clock}",
        "",
        "## 行動原則",
        principles,
        "",
        "## 会話のしかた",
        CONVERSATION_STYLE.replace("{ai_name}", ai_name),
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
    lines += ["", closing_reminder(ai_name, user_name, time_period(time_of_day) if time_of_day else None)]
    return "\n".join(lines)
