"""初回設定の質問と同意文。

質問の順番と文章は仕様で固定されている。変更しないこと（テストで検証している）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetupQuestion:
    key: str
    text: str


SETUP_QUESTIONS: tuple[SetupQuestion, ...] = (
    SetupQuestion("setup.q1_identity", "あなたは誰ですか？"),
    SetupQuestion("setup.q2_personality", "あなたはどんな性格で嫌いなのか好きなのか自分について詳しく教えて下さい"),
    SetupQuestion("setup.q3_ai_name", "私の名前をどうしますか？"),
)

# 同意文を変更したらバージョンを上げる（どの文面に同意したかを記録するため）
CONSENT_VERSION = "2026-11-02.1"

CONSENT_PURPOSE = (
    "このAIがあなたの「第二の自分」としてあなたを理解し、あなたに合った会話・提案・反論を行うために使用します。"
)

CONSENT_STORED_ITEMS: tuple[str, ...] = (
    "初回の3つの質問への回答（あなたが誰か・性格や好き嫌い・AIの名前）",
    "AIの名前と基本設定（使用モデルなど）",
    "この同意の記録（同意日時・同意文のバージョン）",
)

CONSENT_NOTES: tuple[str, ...] = (
    "データはこのPC内（data フォルダー）にのみ保存され、外部へ送信されません。",
    "AIの処理もこのPC上のローカルLLM（Ollama）で行います。",
    "現時点（Phase 1）では会話の内容はサーバーに保存されません。ブラウザーを閉じると消えます。",
    "保存した内容は設定画面からいつでも確認・修正できます。",
    "現時点では保存データは暗号化されていません（暗号化は Phase 2 で実装予定）。共有PCでの利用は避けてください。",
)
