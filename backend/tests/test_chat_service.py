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


def test_system_prompt_conversation_style_and_closing_reminder() -> None:
    from app.schemas import ProfileEntry

    name = ProfileEntry(
        key="self.user_name", question="呼んでほしい名前", content="ケン", source="user_edit", importance=10,
        confirmation_status="confirmed", created_at="", updated_at="",
    )
    prompt = build_system_prompt("タニス", [name], time_of_day="21:30", extra="## カレンダー")
    assert "## 会話のしかた" in prompt
    assert "ユーザーの名前（呼び方）は「ケン」" in prompt
    assert "今の時刻は 21:30（夜）" in prompt
    # 念押しは最後に置く（カレンダーなどの追加情報より後）
    assert prompt.rstrip().splitlines()[0] == "あなたの名前は「タニス」です。"
    closing = prompt[prompt.index("## 最後に"):]
    assert prompt.index("## カレンダー") < prompt.index("## 最後に")
    assert "ユーザー（ケン）とは別の存在" in closing
    assert "今は夜なので、あいさつするなら「こんばんは」を使い、「おはよう」・「こんにちは」とは言わない" in closing
    # あいさつされていなければ、あいさつしない（毎回「こんばんは」から始めない）
    assert "それ以外は、あいさつを付けずにすぐ本題に入る" in closing
    assert "あいさつしていなければ、あいさつから始めない" not in closing  # 1行にまとめた
    # 朝は「おはよう」、昼は「こんにちは」を使う
    morning = build_system_prompt("タニス", [], time_of_day="07:30").split("## 最後に")[1]
    assert "「おはよう」を使い、「こんにちは」・「こんばんは」とは言わない" in morning
    noon = build_system_prompt("タニス", [], time_of_day="13:00").split("## 最後に")[1]
    assert "「こんにちは」を使い、「おはよう」・「こんばんは」とは言わない" in noon
    # 時刻が分からなければ、使う言葉は指定せず、あいさつから始めないことだけ伝える
    unknown = build_system_prompt("タニス", []).split("## 最後に")[1]
    assert "あいさつするなら「" not in unknown
    assert "あいさつしていなければ、あいさつから始めない" in unknown


def test_system_prompt_says_ai_name_is_self_not_third_person() -> None:
    # 「はやと、今日何してた？」に「はやとに聞いて」と返していた不具合の回帰テスト
    prompt = build_system_prompt("はやと", [])
    head = prompt[: prompt.index("## 行動原則")]
    assert "「はやと」はあなた自身の名前で、別の人の名前ではありません。" in head
    assert "「ねえ、はやと」と話しかけたりしたら、それはあなたへの呼びかけです。" in head
    assert "はやとを第三者として扱いません" in head
    assert "読みは" not in head  # 読みが未設定なら書かない
    closing = prompt[prompt.index("## 最後に"):]
    assert "「はやと」はあなたの名前。そう呼ばれたら自分への呼びかけ" in closing
    # 記憶がなければ記憶についての注意は入れない
    assert "あなた（AI）のこと" not in prompt


def test_system_prompt_includes_reading_once() -> None:
    from app.services.persona import name_forms

    assert name_forms("隼人", "はやと") == ["隼人", "はやと"]
    assert name_forms("はやと", "はやと") == ["はやと"]
    assert name_forms(" はやと ", "") == ["はやと"]
    prompt = build_system_prompt("隼人", [], memories=["ユーザーははやとと話すのが好き"], ai_reading="はやと")
    assert "「隼人」（読みは「はやと」）はあなた自身の名前" in prompt
    assert "ユーザーが「隼人」・「はやと」（" in prompt
    assert "記憶やプロフィールに「隼人」・「はやと」が出てきたら、それはあなた（AI）のこと" in prompt


def test_system_prompt_has_date_and_no_realtime_rule() -> None:
    from datetime import date

    prompt = build_system_prompt("タニス", [], today=date(2026, 11, 2))
    assert "2026年11月2日（月）" in prompt
    assert "でっち上げない" in prompt
    assert "ユーザー本人ではなく" in prompt


def test_self_intro_request_and_instruction() -> None:
    from app.services.persona import is_self_intro_request, self_intro_instruction

    for text in ("自己紹介して", "自己紹介してや", "あなたは誰？", "君って何者？", "誰なん？"):
        assert is_self_intro_request(text), text
    for text in ("おすすめの勉強法ある？", "明日の予定は？"):
        assert not is_self_intro_request(text), text
    instruction = self_intro_instruction("ミナ")
    assert "名前はミナ" in instruction
    assert "自己紹介では一切触れない" in instruction
    # 例の言葉をなぞらないよう、具体例は書かない
    assert "ゲーム" not in instruction
    prompt = build_system_prompt("ミナ", [], final=instruction)
    assert prompt.rstrip().endswith(instruction.splitlines()[-1])


def test_system_prompt_gives_ai_its_own_character() -> None:
    prompt = build_system_prompt("タニス", [], time_of_day="21:30")
    head, closing = prompt.split("## 最後に")
    # ユーザーの分身ではなく、別の人格として話す
    assert "第二の自分" not in prompt
    assert "## あなた自身（タニス）について" in head
    assert "ユーザーとは別の人格" in head
    assert "あなた自身（タニス）を紹介する" in head
    # 性格は似ているが、意見は自分のもの
    assert "ユーザーの性格に似ている" in head
    assert "意見は自分のものを持つ" in head
    assert "客観的に見て" in head
    # 理解しているから注意・相談・提案をする
    assert "責めずに、理由を添えて一言伝える" in head
    assert "選択肢と自分のおすすめを理由つきで伝える" in head
    assert "似ているのは性格（気質）と話し方だけ" in head
    # 話し方を合わせ、英単語を混ぜない
    assert "あなたも同じ方言・同じくだけ具合で話す" in closing
    assert "文の途中に英単語を混ぜない" in closing
    english = build_system_prompt("タニス", [], language="en").split("## 最後に")[1]
    assert "英単語を混ぜない" not in english
    assert "タニス自身（性格・役割）を紹介する" in closing
    assert "ただ同意するだけにしない" in closing
    assert "「自分も好き」「〜も好きやから」と言わない" in closing
    assert "「前に〜って言ってたよね」と作らない" in closing
    assert "あいさつするなら「こんばんは」を使い" in closing
