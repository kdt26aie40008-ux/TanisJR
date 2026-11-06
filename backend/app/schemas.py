"""API の入出力スキーマ（入力値検証を含む）。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.languages import LanguageCode

MAX_ANSWER_LEN = 4000
MAX_MESSAGE_LEN = 8000
MAX_MESSAGES = 100

# 制御文字（改行・タブを除く）
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Ollama のモデル名: 例 qwen3:8b, hf.co/user/model:Q4_K_M
MODEL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,127}(:[A-Za-z0-9._\-]{1,64})?$"


def clean_text(value: str) -> str:
    return _CONTROL_CHARS.sub("", value).strip()


SttModelName = Literal["large-v3-turbo", "medium", "small", "base"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_ai_name(value: str) -> str:
    value = clean_text(value)
    if not value:
        raise ValueError("AIの名前を入力してください。")
    if "\n" in value or "\r" in value:
        raise ValueError("AIの名前に改行は使えません。")
    return value


class SetupCompleteRequest(StrictModel):
    consent: bool
    answers: list[str] = Field(min_length=3, max_length=3)
    ai_name: str = Field(min_length=1, max_length=32)

    @field_validator("answers")
    @classmethod
    def _answers(cls, values: list[str]) -> list[str]:
        cleaned = [clean_text(v) for v in values]
        for v in cleaned:
            if not v:
                raise ValueError("すべての質問に回答してください。")
            if len(v) > MAX_ANSWER_LEN:
                raise ValueError(f"回答は{MAX_ANSWER_LEN}文字以内で入力してください。")
        return cleaned

    @field_validator("ai_name")
    @classmethod
    def _ai_name(cls, value: str) -> str:
        return _validate_ai_name(value)


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LEN)

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        value = clean_text(value)
        if not value:
            raise ValueError("メッセージが空です。")
        return value


ID_PATTERN = r"^[0-9a-f]{32}$"


class ChatRequest(StrictModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    # 指定された場合のみ、このターンを保存する（保存を許可された会話）
    conversation_id: str | None = Field(default=None, pattern=ID_PATTERN)

    @field_validator("messages")
    @classmethod
    def _last_is_user(cls, values: list[ChatMessage]) -> list[ChatMessage]:
        if values[-1].role != "user":
            raise ValueError("最後のメッセージはユーザーの発言である必要があります。")
        return values


class AppSettings(StrictModel):
    ai_name: str = Field(default="", max_length=32)
    model: str = Field(default="qwen3:8b", pattern=MODEL_NAME_PATTERN)
    # GPU メモリ不足時に使う代替モデル（空なら使わない）
    fallback_model: str = Field(default="", max_length=192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    num_ctx: int = Field(default=4096, ge=1024, le=32768)
    think: bool = False
    # --- 記憶 (Phase 2) ---
    # 新しい会話を保存するかの既定値。プライバシーのため既定は「保存しない」
    save_conversations_default: bool = False
    # 保存した会話から記憶を自動抽出するか
    auto_extract: bool = True
    embedding_model: str = Field(default="qwen3-embedding:0.6b", pattern=MODEL_NAME_PATTERN)
    rag_max_results: int = Field(default=5, ge=0, le=20)
    # cosine 距離のしきい値。これより遠い記憶は会話に入れない
    rag_max_distance: float = Field(default=0.5, ge=0.0, le=1.0)
    # --- 音声・アバター (Phase 3) ---
    stt_model: SttModelName = "large-v3-turbo"
    # GPU は LLM が使うため既定は CPU
    stt_device: Literal["cpu", "cuda"] = "cpu"
    stt_auto_send: bool = True
    # 話し終わり（無音）を検出したら自動で録音を終える
    voice_auto_stop: bool = True
    # 何ミリ秒黙ったら話し終わりとみなすか
    voice_silence_ms: int = Field(default=1200, ge=500, le=4000)
    # 返事のあと、続けて聞き取りを始める（止めるまで声で会話を続ける）
    voice_handsfree: bool = False
    # 会話の言語（聞き取りと返事）。読み上げは日本語のみ対応
    language: LanguageCode = "ja"
    # --- ふるまい（会話の自然さ） ---
    # 聞いている間うなずく
    behavior_nod: bool = True
    # 目線をこちら（画面の前の人・マウスの位置）に向ける
    behavior_gaze: bool = True
    # 話し終わったら短い相づちを返す
    behavior_backchannel: bool = True
    # AI が話している途中でも、話しかけたら止まって聞く（マイクの音を拾うのでヘッドホン推奨のため既定はオフ）
    behavior_barge_in: bool = False
    # 文ごとに表情を変える
    behavior_sentence_emotion: bool = True
    # --- 自分から話しかける（アプリを開いている間のみ） ---
    proactive_enabled: bool = False
    # 朝、その日はじめて開いたときにあいさつする
    proactive_morning: bool = True
    # 予定の何分前に声をかけるか（0 で声をかけない）
    proactive_event_minutes: int = Field(default=15, ge=0, le=120)
    # 何時間話していなかったら声をかけるか（0 で声をかけない）
    proactive_idle_hours: int = Field(default=3, ge=0, le=24)
    # 話しかけない時間帯（開始・終了。日付をまたいでよい）
    quiet_start: str = Field(default="23:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    # --- 「ねえ○○」で起きる（専用の操作でのみ有効にする。同意と「あなたのこと」の入力が必要） ---
    wake_enabled: bool = False
    # AI の名前の読み（ひらがな・カタカナ）。漢字の名前を聞き取りやすくするため
    wake_reading: str = Field(default="", max_length=32)
    tts_speaker: int | None = Field(default=None, ge=0)
    tts_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_auto_read: bool = True
    # AivisSpeech のアプリ画面を開かなくても、読み上げエンジンだけを自動で起動する
    tts_engine_autostart: bool = True
    # 利用規約を確認した AivisSpeech の話者 (speaker_uuid)
    tts_acknowledged_speakers: list[str] = Field(default_factory=list)
    avatar_id: str = ""
    # --- カレンダー・通知 (Phase 4) ---
    # 予定の保存先。local: アプリ内（この PC のこのユーザーだけ）/ google: Google カレンダー
    calendar_backend: Literal["local", "google"] = "local"
    notifications_enabled: bool = True
    # 予定の何分前に通知するか（予定ごとの設定がない場合）
    default_reminder_minutes: int = Field(default=10, ge=0, le=1440)
    # 会話から予定の追加・変更・削除の下書きを提案する（実行は承認後のみ）
    calendar_ai_proposals: bool = True

    @field_validator("fallback_model")
    @classmethod
    def _fallback(cls, value: str) -> str:
        value = value.strip()
        if value and not re.match(MODEL_NAME_PATTERN, value):
            raise ValueError("代替モデル名の形式が正しくありません。")
        return value


class SettingsUpdate(StrictModel):
    """部分更新。指定された項目だけ変更する。"""

    ai_name: str | None = Field(default=None, min_length=1, max_length=32)
    model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    fallback_model: str | None = Field(default=None, max_length=192)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    num_ctx: int | None = Field(default=None, ge=1024, le=32768)
    think: bool | None = None
    save_conversations_default: bool | None = None
    auto_extract: bool | None = None
    embedding_model: str | None = Field(default=None, pattern=MODEL_NAME_PATTERN)
    rag_max_results: int | None = Field(default=None, ge=0, le=20)
    rag_max_distance: float | None = Field(default=None, ge=0.0, le=1.0)
    stt_model: SttModelName | None = None
    stt_device: Literal["cpu", "cuda"] | None = None
    stt_auto_send: bool | None = None
    voice_auto_stop: bool | None = None
    voice_silence_ms: int | None = Field(default=None, ge=500, le=4000)
    voice_handsfree: bool | None = None
    language: LanguageCode | None = None
    behavior_nod: bool | None = None
    behavior_gaze: bool | None = None
    behavior_backchannel: bool | None = None
    behavior_barge_in: bool | None = None
    behavior_sentence_emotion: bool | None = None
    proactive_enabled: bool | None = None
    proactive_morning: bool | None = None
    proactive_event_minutes: int | None = Field(default=None, ge=0, le=120)
    proactive_idle_hours: int | None = Field(default=None, ge=0, le=24)
    quiet_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    wake_reading: str | None = Field(default=None, max_length=32)
    tts_speaker: int | None = Field(default=None, ge=0)
    tts_speed: float | None = Field(default=None, ge=0.5, le=2.0)
    tts_auto_read: bool | None = None
    tts_engine_autostart: bool | None = None
    calendar_backend: Literal["local", "google"] | None = None
    notifications_enabled: bool | None = None
    default_reminder_minutes: int | None = Field(default=None, ge=0, le=1440)
    calendar_ai_proposals: bool | None = None

    @field_validator("ai_name")
    @classmethod
    def _ai_name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_ai_name(value)


class ProfileEntry(BaseModel):
    key: str
    question: str | None
    content: str
    source: str
    importance: int
    confirmation_status: str
    created_at: str
    updated_at: str


class ProfileUpdate(StrictModel):
    key: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=MAX_ANSWER_LEN)

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        value = clean_text(value)
        if not value:
            raise ValueError("内容を入力してください。")
        return value


# 設定「あなたのこと」で本人が入力する項目（初回の3問とは別。初回の3問は変更しない）
SELF_PROFILE_FIELDS: dict[str, str] = {
    "self.user_name": "呼んでほしい名前",
    "self.personality": "あなたの個性（性格・価値観・好き嫌い）",
    "self.traits": "あなたの特徴（口ぐせ・話し方・生活のリズムなど）",
}


# ===== 記憶・会話 (Phase 2) =====

MemoryCategory = Literal["preference", "habit", "fact", "personal", "personality", "values", "other"]
# 保存前に本人の確認が必要なカテゴリ（個人情報・性格・価値観）
IMPORTANT_CATEGORIES: frozenset[str] = frozenset({"personal", "personality", "values"})
MAX_MEMORY_LEN = 500


class Memory(BaseModel):
    id: str
    category: str
    content: str
    source_type: str
    source_conversation_id: str | None
    source_conversation_title: str | None = None
    source_excerpt: str | None
    importance: int
    sensitivity: str
    status: str
    confirmation_status: str
    indexed: bool
    created_at: str
    updated_at: str


def _memory_content(value: str) -> str:
    value = clean_text(value)
    if not value:
        raise ValueError("記憶の内容を入力してください。")
    return value


class MemoryCreate(StrictModel):
    content: str = Field(min_length=1, max_length=MAX_MEMORY_LEN)
    category: MemoryCategory = "other"
    importance: int = Field(default=5, ge=1, le=10)

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        return _memory_content(value)


class MemoryUpdate(StrictModel):
    content: str | None = Field(default=None, min_length=1, max_length=MAX_MEMORY_LEN)
    category: MemoryCategory | None = None
    importance: int | None = Field(default=None, ge=1, le=10)

    @field_validator("content")
    @classmethod
    def _content(cls, value: str | None) -> str | None:
        return None if value is None else _memory_content(value)


class ConversationCreate(StrictModel):
    # 保存を有効にした時点までの会話（空でもよい）
    messages: list[ChatMessage] = Field(default_factory=list, max_length=MAX_MESSAGES)


class ConversationSummary(BaseModel):
    id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class StoredMessage(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


class ConversationDetail(ConversationSummary):
    messages: list[StoredMessage]


class BackupRequest(StrictModel):
    passphrase: str = Field(min_length=1, max_length=256)


class RestoreRequest(StrictModel):
    passphrase: str = Field(min_length=1, max_length=256)
    # バックアップファイルの内容 (base64)
    data: str = Field(min_length=1, max_length=280 * 1024 * 1024)


# ===== 音声・アバター (Phase 3) =====


class TtsRequest(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    # 未指定なら設定の話者を使う（設定画面の試聴用に指定可能）
    speaker: int | None = Field(default=None, ge=0)


class SpeakerAck(StrictModel):
    speaker_uuid: str = Field(min_length=1, max_length=64, pattern=r"^[0-9a-fA-F-]+$")


class WhisperDownloadRequest(StrictModel):
    model: SttModelName
    confirmed: bool


class AvatarUpdate(StrictModel):
    name: str | None = Field(default=None, max_length=64)
    is_placeholder: bool | None = None


class ModelPullRequest(StrictModel):
    model: str = Field(pattern=MODEL_NAME_PATTERN)
    # ユーザーがサイズと保存先を確認した上で操作したことを示す
    confirmed: bool
