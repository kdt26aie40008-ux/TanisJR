"""会話の言語。聞き取り（Whisper）と返事の言語に使う。

読み上げ（AivisSpeech）は日本語専用のため、日本語以外では読み上げを使わない。
"""

from __future__ import annotations

from typing import Literal

LanguageCode = Literal["ja", "en", "zh", "ko", "es", "fr", "de"]

# コード → 表示名（設定画面と、AI への指示に使う）
LANGUAGE_NAMES: dict[str, str] = {
    "ja": "日本語",
    "en": "英語",
    "zh": "中国語",
    "ko": "韓国語",
    "es": "スペイン語",
    "fr": "フランス語",
    "de": "ドイツ語",
}

# 読み上げに対応している言語
TTS_LANGUAGES = frozenset({"ja"})
