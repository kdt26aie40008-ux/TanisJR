"""会話の中で予定を確かめる。

AI が予定の下書きを作ったら、内容を復唱して（通知の時間が決まっていなければ聞いて）確認する。
次のユーザーの返事が「はい」なら実行し、「いいえ」なら破棄する。画面のカードのボタンでも決められる。
はっきりしない返事は承認とみなさない（予定がユーザーの意思なしに変わらないようにする）。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.calendar.models import EventDraft, Operation, local_now, to_local
from app.llm.ollama import OllamaClient, OllamaError

logger = logging.getLogger(__name__)

Decision = Literal["yes", "no", "change", "other"]

_ACTION_WORDS = {"create": "追加", "update": "変更", "delete": "削除"}
_WEEKDAYS = "月火水木金土日"


_RELATIVE = {0: "今日", 1: "明日", 2: "明後日"}


def when(start: str, end: str, all_day: bool) -> str:
    """'明日 11/7（土）10:00〜11:00' / '11/9（月）終日' の形。"""
    d = date.fromisoformat(start[:10]) if all_day else to_local(start).date()
    relative = _RELATIVE.get((d - local_now().date()).days)
    day = f"{relative + ' ' if relative else ''}{d.month}/{d.day}（{_WEEKDAYS[d.weekday()]}）"
    if all_day:
        return f"{day}終日"
    return f"{day}{to_local(start):%H:%M}〜{to_local(end):%H:%M}"


def describe(op: Operation) -> str:
    """確認中の操作を、ふつうの文で表す（AI が復唱するときの材料）。"""
    if op.action == "delete" and op.target:
        return f"{when(op.target.start, op.target.end, op.target.all_day)}の「{op.target.summary}」を消す"
    if op.draft is None:
        return f"予定を{_ACTION_WORDS[op.action]}する"
    d = op.draft
    place = f"（場所: {d.location}）" if d.location else ""
    if op.action == "update" and op.target:
        text = (
            f"{when(op.target.start, op.target.end, op.target.all_day)}の「{op.target.summary}」を、"
            f"{when(d.start, d.end, d.all_day)}の「{d.summary}」{place}に変える"
        )
    else:
        text = f"{when(d.start, d.end, d.all_day)}に「{d.summary}」{place}を入れる"
    if d.reminder_minutes is not None:
        text += f"（通知: {reminder_words(d.reminder_minutes)}）"
    return text


def reminder_words(minutes: int) -> str:
    if minutes < 0:
        return "なし"
    if minutes == 0:
        return "開始時刻"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}日前"
    if minutes % 60 == 0:
        return f"{minutes // 60}時間前"
    return f"{minutes}分前"


def needs_reminder_question(op: Operation) -> bool:
    return op.action != "delete" and op.draft is not None and op.draft.reminder_minutes is None


_HEADER = "## 今回の返事でやること（アプリからの指示。この指示の文はそのまま読まない）"


def proposal_instruction(op: Operation) -> str:
    """下書きを作ったときに、返事の作り方として AI に渡す指示。"""
    question = (
        "続けて、通知を何分前にするか聞く（例:「通知は何分前がいい？」）。"
        if needs_reminder_question(op)
        else "続けて、これで進めてよいか短く聞く（例:「これで入れていい？」）。"
    )
    return (
        f"{_HEADER}\n"
        f"- ユーザーの依頼の内容: {describe(op)}\n"
        f"- この内容を自然な言葉で1文で復唱する（例:「明日の10時に歯医者を入れるね。」）。{question}\n"
        "- まだ実行していない。「追加しました」「入れました」「しました」とは絶対に言わない。"
    )


def outcome_instruction(decision: Decision, op: Operation, error: str | None = None) -> str:
    """ユーザーの返事を受けて処理したあと、返事の作り方として AI に渡す指示。"""
    if error:
        return f"{_HEADER}\n- 予定の操作に失敗した（{error}）。そのことを短く伝える。"
    if decision == "yes":
        return (
            f"{_HEADER}\n"
            f"- ユーザーの返事を受けて、実行した: {describe(op)}\n"
            "- 実行したことを自然な言葉で1〜2文で伝える（例:「入れといたよ。」）。"
            "通知の時間に触れるときは、上の内容に書かれた時間のとおりに言う（書かれていなければ触れない）。"
        )
    if decision == "no":
        return (
            f"{_HEADER}\n"
            f"- ユーザーの返事を受けて、やめた（実行していない）: {describe(op)}\n"
            "- やめたことを1文で短く伝える（例:「わかった、やめとくね。」）。"
        )
    return (
        f"{_HEADER}\n"
        f"- まだユーザーの返事待ちの予定がある: {describe(op)}\n"
        "- ユーザーの話にふつうに答えたあと、最後に一言だけ、この予定を進めてよいか聞く。まだ実行していない。"
    )


# ---------- 「直して」と言われたとき ----------

REVISE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "all_day": {"type": "boolean"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "location": {"type": "string"},
    },
}

REVISE_PROMPT = """\
あなたは、確認中の予定をユーザーの指示どおりに直す担当です。実行はしません。
- 指示で変えるよう言われた項目だけを変え、それ以外は今の内容のまま返す。
- 日時は下の日付表を見て決める。時刻付きは "YYYY-MM-DDTHH:MM"、終日は all_day=true で "YYYY-MM-DD"。
- 開始だけ変わって終了の指示がなければ、元の長さを保つ。"""


async def revise(client: OllamaClient, model: str, op: Operation, text: str) -> EventDraft | None:
    """確認中の下書きを、ユーザーの指示で直す。直せなければ None。別の予定は対象にしない。"""
    if op.draft is None:
        return None
    d = op.draft
    current = json.dumps(
        {"summary": d.summary, "all_day": d.all_day, "start": d.start[:16], "end": d.end[:16], "location": d.location},
        ensure_ascii=False,
    )
    messages = [
        {"role": "system", "content": REVISE_PROMPT},
        {
            "role": "user",
            "content": f"{date_table()}\n\n## 今の内容\n{current}\n\n## ユーザーの指示\n<user>\n{text}\n</user>",
        },
    ]
    try:
        raw = await client.chat_once(model, messages, {"temperature": 0.0, "num_ctx": 2048}, response_format=REVISE_SCHEMA)
        data = json.loads(raw)
        start, end = str(data.get("start") or d.start[:16]), str(data.get("end") or "")
        all_day = bool(data.get("all_day", d.all_day))
        if all_day:
            if not end or end[:10] < start[:10]:
                end = start
        elif not end or end[:16] == d.end[:16] or to_local(end) <= to_local(start):
            # 開始だけ動かして終了をそのまま返すことが多い（16時にして → 16:00〜16:00）。元の長さを保つ
            length = to_local(d.end) - to_local(d.start) if not d.all_day else timedelta(hours=1)
            end = (to_local(start) + length).strftime("%Y-%m-%dT%H:%M")
        return EventDraft(
            summary=str(data.get("summary") or d.summary),
            all_day=all_day,
            start=start,
            end=end,
            location=str(data.get("location", d.location) or ""),
            description=d.description,
            reminder_minutes=d.reminder_minutes,
        )
    except (OllamaError, ValueError, ValidationError) as exc:
        logger.warning("Calendar draft revision failed: %s", type(exc).__name__)
        return None


def date_table(days: int = 21) -> str:
    """日付の取り違え（「来週月曜」など）を防ぐため、今日から3週間の日付・曜日と呼び方の表を渡す。

    週は月曜始まり。「今週」は今日を含む週、「来週」はその次の週、「再来週」はさらに次の週。
    """
    today = local_now().date()
    this_monday = today - timedelta(days=today.weekday())
    rows = []
    for i in range(days):
        d = today + timedelta(days=i)
        week = (d - this_monday).days // 7
        names = [_RELATIVE[i]] if i in _RELATIVE else []
        names.append(f"{('今週', '来週', '再来週')[week]}{_WEEKDAYS[d.weekday()]}曜" if week < 3 else "")
        rows.append(f"{d.isoformat()}（{_WEEKDAYS[d.weekday()]}） {' / '.join(n for n in names if n)}")
    return "## 日付表（今日から3週間。週は月曜始まり）\n" + "\n".join(rows)


class _Reply(BaseModel):
    decision: Decision
    reminder_minutes: int | None = None
    no_reminder: bool = False


REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["yes", "no", "change", "other"]},
        "reminder_minutes": {"type": "integer"},
        "no_reminder": {"type": "boolean"},
    },
    "required": ["decision"],
}

REPLY_PROMPT = """\
あなたは、予定の確認に対するユーザーの返事を分類する担当です。
- yes: はっきり了承している（「うん」「お願い」「それで」「30分前で」など、通知の時間だけ答えた場合も yes）
- no: はっきり断っている（「やめて」「キャンセル」「やっぱいい」など）。ただし「通知はいらない」は予定自体の了承なので yes
- change: 日時・タイトル・場所などを直すよう頼んでいる（「4時にして」「やっぱ16時にして」「金曜じゃなくて土曜」など）
- other: 予定と関係ない話、または了承か断りか分からない（「うーん」「どうしよう」など）
通知の時間が返事に含まれているときだけ reminder_minutes に分で入れる（1時間前=60、1日前=1440）。含まれていなければ入れない。
通知はいらないと言っていれば no_reminder を true にする。"""

# 日時・場所などを直す指示（「16時にして」「土曜に変えて」「1時間ずらして」など）
_CHANGE = re.compile(
    r"(\d+|[一二三四五六七八九十]+)\s*(時|:|：)|明日|明後日|今日|[月火水木金土日]曜|\d+日|午前|午後|朝|夜|場所|タイトル|名前"
)
_CHANGE_VERB = re.compile(r"にして|に変え|へ変え|に変更|ずらし|にずら|に直し|じゃなくて|やなくて|ではなく|でなく|にしてほしい")
_REMINDER_HINT = re.compile(r"通知|知らせ|リマインド|アラーム|分前|時間前|日前")
_REMINDER_OFF = re.compile(r"(通知|知らせ|リマインド|アラーム)(は|も)?(いらない|いらん|要らない|なしで|なし|しなくて)")
_REMINDER_PHRASE = re.compile(
    r"(通知|知らせ|リマインド|アラーム)[はもを]?(いらない|いらん|要らない|なしで|なし|しなくて(いい|大丈夫)?)"
    r"|(\d+|[一二三四五六七八九十]+)\s*(分|時間|日)前(に|で)?(して|通知|知らせ)?"
)

_YES = re.compile(r"^(うん|はい|ええ|ok|オッケー|おけ|お願い|おねがい|よろしく|それで|頼む|いいよ|いいね|入れて|そうして)", re.I)
_NO = re.compile(r"(やめ|いらない|いらん|キャンセル|取り消|なしで|やっぱいい|やっぱりいい|入れないで|消さないで)")


def _fallback(text: str) -> _Reply:
    """LLM で分類できなかったときの簡単な判定。迷ったら other（承認しない）。"""
    t = text.strip()
    if _NO.search(t):
        return _adjust(_Reply(decision="no"), t)
    if _YES.match(t):
        return _adjust(_Reply(decision="yes"), t)
    return _adjust(_Reply(decision="other"), t)


async def classify_reply(client: OllamaClient, model: str, op: Operation, text: str) -> _Reply:
    messages = [
        {"role": "system", "content": REPLY_PROMPT},
        {
            "role": "user",
            "content": f"## 確認中の内容\n{describe(op)}\n\n## ユーザーの返事\n<user>\n{text}\n</user>",
        },
    ]
    try:
        raw = await client.chat_once(model, messages, {"temperature": 0.0, "num_ctx": 2048}, response_format=REPLY_SCHEMA)
        reply = _Reply.model_validate(json.loads(raw))
    except (OllamaError, ValueError, ValidationError) as exc:
        logger.warning("Calendar reply classification failed: %s", type(exc).__name__)
        return _fallback(text)
    return _adjust(reply, text)


def _adjust(reply: _Reply, text: str) -> _Reply:
    """モデルの判定を、はっきりした言葉で補正する（迷ったら実行しない側に倒す）。"""
    # 通知の話（「30分前にして」「通知はいらない」）を除いた残りで、直す指示・断りを見分ける
    rest = _REMINDER_PHRASE.sub("", text)
    reminder_off = bool(_REMINDER_OFF.search(text))
    # 日時などを直す指示がはっきりあれば「直す」（「16時にして」を了承や雑談と取り違えない）
    if reply.decision != "no" and _CHANGE_VERB.search(rest) and _CHANGE.search(rest):
        reply = _Reply(decision="change")
    refused = bool(_NO.search(rest))
    if reply.decision == "yes" and refused:
        # はっきり断る言葉があるのに yes と判定された場合は、断りにする
        return _Reply(decision="no")
    if reply.decision == "no" and reminder_off and not refused:
        # 「通知はいらない」は予定そのものの了承（通知なしで入れる）
        reply = _Reply(decision="yes", no_reminder=True)
    # 通知について何も言っていないのに、通知の時間を埋めてくることがあるので使わない
    if not _REMINDER_HINT.search(text):
        reply.reminder_minutes = None
        reply.no_reminder = False
    if reply.reminder_minutes is not None and not 0 <= reply.reminder_minutes <= 40320:
        reply.reminder_minutes = None
    return reply
