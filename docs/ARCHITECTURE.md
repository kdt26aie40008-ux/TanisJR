# AnotherMe（もう一人の私）設計書

> 旧称: 第二の自分AI（Personal Twin AI）。データの保存先（`%LOCALAPPDATA%\PersonalTwinAI`）・暗号鍵の保護に使う識別子・自動起動のショートカット名（`PersonalTwinAI.lnk`）は、既存のデータと設定を引き継ぐため旧名のまま。

> このファイルは設計方針の正本。コンテキストが途切れても開発を継続できるよう、設計判断はここに記録する。
> 進捗・未完了タスクは [PROGRESS.md](PROGRESS.md) を参照。

## 1. 全体構成

```
┌──────────────────── ブラウザー (http://127.0.0.1:8765) ────────────────────┐
│ React + TypeScript (Vite)                                                  │
│  初回設定 / チャット / 設定 / (記憶・音声・アバター・カレンダー・学習: 後続)  │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ fetch (JSON) / SSE ストリーム（同一オリジン）
┌───────────────▼──────────── FastAPI (127.0.0.1:8765 のみ待ち受け) ──────────┐
│ security: Host検証(DNSリバインディング対策) / Origin検証(CSRF対策) / CSP     │
│ routers: health, setup, chat, settings, profile, models                     │
│ services: persona(プロンプト構築), chat(フォールバック付き推論)             │
│ storage: SQLite (data/twin.db)   [Phase2: ChromaDB, 暗号化]                  │
└───────────────┬────────────────────────────────────────────────────────────┘
                │ HTTP (localhost限定)
        ┌───────▼────────┐
        │ Ollama          │  qwen3:8b (Q4_K_M, 約5.2GB, RTX 5060 8GB で 100% GPU)
        └────────────────┘
```

- 本番時は FastAPI がビルド済みフロントエンド (`frontend/dist`) を配信する（1ポート構成）。
- 開発時は Vite (5173) → FastAPI (8765) へプロキシ。

## 2. 設計方針

| 項目 | 方針 |
|---|---|
| データの保存先 | **PC・Windows ユーザーごと** に `%LOCALAPPDATA%\PersonalTwinAI\data`（本書の `data/` はこのフォルダーを指す）。アカウントの仕組みは作らない。プロジェクトフォルダーを他の PC・ユーザーで使っても個人データは移らず、新しい人は空の状態から始まる。旧保存先（プロジェクト内 `data/`）は、鍵をこのユーザーの DPAPI で読める場合だけ起動時に移動する（`app/data_location.py`）。ロック時は「新しく始める」で退避して空から開始できる |
| 通信 | サーバーは `127.0.0.1` にのみバインド。Ollama URL もローカルホスト以外は起動時に拒否。外部通信は明示的な機能（モデルDL、Google Calendar、天気予報（設定でオンにしたときだけ Open-Meteo に場所の緯度・経度を送る））に限定。スマホからの利用は Tailscale の中継経由だけ（9C） |
| 不正アクセス対策 | `TrustedHostMiddleware` で Host ヘッダーを `127.0.0.1`/`localhost` に限定（DNSリバインディング対策）。状態変更リクエストは Origin を許可リストで検証（CSRF対策） |
| 会話データ | **Phase 1 ではサーバー側に会話を一切永続化しない**。履歴はブラウザーのメモリ上のみ。ログにも本文を出力しない。保存選択は Phase 2 で実装 |
| 人格 | 固定文ではなく「行動原則 + プロフィール + (Phase2: 長期記憶RAG) + 会話文脈」から毎回システムプロンプトを組み立てる (`app/services/persona.py`)。AI はユーザーの分身ではなく別の人格: 性格はユーザーに似るが意見は自分で持ち、ユーザーを客観的に見て注意・提案・相談をする（`SELF_CHARACTER`） |
| 推測禁止 | プロフィール/記憶に無いユーザー情報は推測で作らないようプロンプトで明示 |
| GPU不足 | OOM 検出時にフォールバック: ①コンテキスト長縮小 → ②CPU実行(num_gpu=0) → ③設定済みの代替モデル。トークン出力開始後は再試行しない |
| モデルDL | 自動DLしない。サイズ（目安）と保存先を表示し、ユーザーの確認操作後にのみ `ollama pull` を実行 |
| 初回質問 | 3問の文言は `app/setup_questions.py` が唯一の正本。フロントは API から取得して表示する |
| 同意 | 初回設定で利用目的・保存内容を提示し、同意（バージョン付き）を `consents` に記録。同意なしではプロフィールを保存しない |
| エラー | バックエンドは `{"detail": {"code", "message"}}`（日本語）で返し、フロントはそのまま表示 |

## 3. データモデル (SQLite: `data/twin.db`)

マイグレーションは `app/db.py` の `MIGRATIONS`（連番）で管理。

- `settings(key, value JSON, updated_at)` — AI名・モデル・温度・思考モード等
- `profile_entries(id, key UNIQUE, question, content, source, importance, confirmation_status, created_at, updated_at)`
  - 記憶種別「1. ユーザーが明示的に提供したプロフィール情報」に相当
  - `source`: `initial_setup` / `user_edit`
- `consents(id, kind, version, granted, granted_at)`

Phase 2 で追加予定: `memories`（AI抽出記憶/承認済み重要情報、出典・重要度・確認状態付き）、`pending_memories`、`conversations`/`messages`（保存許可分のみ）、`training_examples`。ChromaDB のIDは SQLite の主キーと一致させ、削除は両方をトランザクション的に処理する。

## 4. API (Phase 1)

| メソッド | パス | 内容 |
|---|---|---|
| GET | `/api/health` | サーバー・Ollama 状態 |
| GET | `/api/setup/status` | 初回設定済みか |
| GET | `/api/setup/questions` | 3問と同意文 |
| POST | `/api/setup/complete` | 同意・回答・AI名を一括保存（トランザクション） |
| GET/PUT | `/api/settings` | 基本設定 |
| GET/PUT | `/api/profile` | プロフィール閲覧・修正 |
| POST | `/api/chat` | SSE ストリーム (`token`/`thinking`/`notice`/`error`/`done`) |
| GET | `/api/models/status` | 導入済みモデル・カタログ・保存先 |
| POST | `/api/models/pull` | 確認済みのモデルDL（SSE進捗）。カタログ内モデルのみ |
| GET/POST | `/api/memories` | 記憶の一覧（status/q/category）・手動追加 |
| PUT/DELETE | `/api/memories/{id}` | 修正・削除（SQLite + ChromaDB） |
| POST | `/api/memories/{id}/approve` `/reject` | 承認待ちの承認（修正可）・拒否（削除） |
| GET | `/api/memories/stats` | 件数・索引状態 |
| POST | `/api/memories/reindex` | 整合性確認・再索引 |
| GET/POST | `/api/conversations` | 保存した会話の一覧・作成（保存オン時） |
| GET/DELETE | `/api/conversations/{id}` | 詳細・削除（`delete_memories` で抽出記憶も削除） |
| POST | `/api/backup` / `/api/backup/restore` | 暗号化バックアップの作成・復元 |
| POST | `/api/speech/stt` | 音声（生バイト列, 25MB/120秒まで）→ テキスト |
| GET/POST | `/api/speech/stt/status` `/stt/warmup` `/stt/models/download` | 認識モデルの状態・事前読み込み・確認済みDL |
| GET | `/api/speech/tts/speakers` `/tts/speakers/{uuid}/policy` | 話者一覧（規約確認状態つき）・利用規約 |
| POST | `/api/speech/tts/acknowledge` `/api/speech/tts` | 規約の確認記録・音声合成（wav） |
| GET/POST | `/api/avatars` | アバター一覧・VRM 登録（生バイト列, 100MBまで） |
| GET/PUT/DELETE | `/api/avatars/{id}` `/file` `/activate` | 配信・名前/仮モデル変更・選択・削除 |

チャットの SSE イベント（Phase 2 追加）: `memories_used`（参照した記憶）、`saved`（保存完了）。`conversation_id` を指定した場合のみ保存・抽出する。

## 5. ディレクトリ構成

```
TanisJr/
├─ backend/
│  ├─ app/
│  │  ├─ main.py            アプリ生成・ミドルウェア・静的配信
│  │  ├─ config.py          設定（環境変数）
│  │  ├─ db.py              SQLite接続・マイグレーション
│  │  ├─ security.py        Origin検証・セキュリティヘッダー
│  │  ├─ errors.py          日本語エラー
│  │  ├─ schemas.py         Pydanticモデル（入力検証）
│  │  ├─ setup_questions.py 初回3問・同意文（正本）
│  │  ├─ crypto.py          DPAPI鍵保護・AES-GCM列暗号化・Vault
│  │  ├─ backup.py          パスフレーズ暗号化バックアップ
│  │  ├─ vector_index.py    ChromaDB（IDとベクトルのみ）
│  │  ├─ repositories/      settings, profile, conversations, memories
│  │  ├─ llm/               ollama.py, catalog.py
│  │  ├─ services/          persona, chat, memory(索引・RAG・整合性), extraction, data_protection
│  │  └─ routers/           health, setup, chat, settings, models, memories, data
│  ├─ tests/
│  └─ requirements*.txt
├─ frontend/                React + TS (Vite)
├─ scripts/                 start.ps1, dev.ps1
├─ docs/                    ARCHITECTURE.md, PROGRESS.md
└─ data/                    実行時データ（git管理外）
```

## 6. Phase 2: 記憶・データ保護の設計

### 6.1 暗号化
- マスター鍵（256bit, ランダム生成）を **Windows DPAPI**（ユーザーアカウントに紐づく）で保護し `data/keys/master.key` に保存。ソースコードに鍵は含めない。
- 機密列（プロフィール回答・記憶内容・出典抜粋・会話タイトル・メッセージ本文）は **AES-256-GCM** で列単位に暗号化（`enc:v1:` 接頭辞）。`app/crypto.py`
- `settings.key_check` に既知文字列の暗号文を保存。鍵が無い/復号できない（別PC・Windows再インストール等）場合は **ロック状態** で起動し、データ系APIは 423 を返す。画面はバックアップからの復元のみ提示。
- 検索は復号してアプリ内で行う（個人規模の件数を想定）。
- ChromaDB には **ベクトルとIDのみ** を保存し、本文は保存しない（ベクトル自体は暗号化されない点は既知の制約）。

### 6.2 暗号化バックアップ / 復元 (`app/backup.py`)
- 形式: `TWINBK01` + salt + nonce + AES-256-GCM(zlib(JSON{master_key, SQLiteスナップショット}))。鍵はユーザーのパスフレーズから scrypt で導出。
- パスフレーズさえあれば別PCでも復元可能（DPAPI に依存しない）。
- 復元は SQLite のバックアップAPIで現行DBへ書き戻し → 鍵を DPAPI で再保護 → ChromaDB を再構築。

### 6.3 記憶の種類と保存先

| 種類（仕様6.1） | 保存先 | 確認状態 |
|---|---|---|
| 1. 明示的なプロフィール | `profile_entries` | confirmed |
| 2. 会話から抽出した一般的な記憶 | `memories` (sensitivity=general, status=active) | auto |
| 3. 確認済みの重要情報 | `memories` (sensitivity=important) 承認前は status=pending | pending → confirmed |
| 4. 保存を許可された会話 | `conversations` / `messages` | — |
| 5. 承認済み学習データ | Phase 5 で `training_examples` を追加 | — |

- 重要情報 = カテゴリが personal / personality / values、または LLM が sensitive と判定、または内容に個人情報キーワード（住所・勤務先・健康・家族・お金など。`services/memory.py`）を含む。重要度（会話での有用度）は判定に使わない。
- 拒否した保存待ち情報は削除する（残さない）。
- ChromaDB に入るのは status=active の記憶のみ。承認待ちは RAG に使わない。

### 6.4 会話の保存選択
- 既定は「保存しない」（設定で変更可）。チャット画面のスイッチで会話単位に選択。
- 保存しない会話: サーバーは応答生成にのみ使い、DB・ログ・ベクトルDB・記憶抽出のいずれにも渡さない。RAG 検索のためのクエリ埋め込みはメモリ上で一時的に計算するだけ。
- 保存する会話: 応答完了時にユーザー発言と応答を保存し、レスポンス送信後のバックグラウンド処理で記憶抽出を行う（自動抽出は設定でオフにできる）。中断・エラーになったターンは保存しない。
- 会話削除時は「この会話から抽出された記憶も削除」を選べる。残す場合は記憶の出典が「削除済みの会話」になる。

### 6.5 RAG
- 埋め込み: Ollama `qwen3-embedding:0.6b`（1024次元、約639MB）。検索クエリには指示文を付与。
- ChromaDB コレクションは埋め込みモデルごと（`memories-<model>`、cosine）。モデル変更時は再インデックス。
- 検索: 最新のユーザー発言で上位を取り、**距離しきい値（既定 0.5）** と **最大件数（既定 5）** で絞り込む。該当が無ければ記憶は入れない。
- 使った記憶は `memories_used` イベントで画面に表示（出典の透明性）。
- 整合性: 起動時と手動操作で `reconcile`（ChromaDB 側の孤立IDを削除、未インデックスの記憶を追加）。削除は SQLite トランザクション内で ChromaDB 削除を行い、失敗時はロールバック。

## 7. Phase 3: 音声・3Dアバターの設計

### 7.1 音声認識（faster-whisper, `app/speech/stt.py`）
- 既定モデル `large-v3-turbo`（約1.6GB）を `models/whisper/`（Git管理外）に保存。DL は容量・保存先を提示し確認後のみ。読み込みは `local_files_only=True`（推論時に外部通信しない）。
- **既定は CPU (int8)**。GPU は LLM（qwen3:8b 約5.6GB + 埋め込み約1.2GB）で埋まるため。設定で CUDA を選べ、失敗時は CPU に自動フォールバック。
- ブラウザーの MediaRecorder（webm/opus）をそのまま送信し、PyAV でメモリ上でデコード。**音声はディスクにもログにも保存しない**。
  - faster-whisper 1.2.1 同梱の `decode_audio` は PyAV 19 と非互換（`metadata_errors` 引数）のため、自前のデコーダーを使う。
- 1件ずつ処理（ロック）。VAD で無音を除去。日本語固定。
- 音声会話画面を開いたときに `/api/speech/stt/warmup` でモデル読み込み＋初回推論を済ませる（初回 15秒 → 約5秒）。重い処理はすべてワーカースレッドで行い、他のAPIを止めない。
- 実測（Core Ultra 7 / CPU int8 / large-v3-turbo）: 6秒の音声で約4秒。

### 7.2 音声合成（AivisSpeech Engine, `app/speech/tts.py`）
- AivisSpeech Engine（VOICEVOX 互換 API, `127.0.0.1:10101`）にバックエンド経由で中継。URL はローカルホスト限定。
- 話者（スタイル）ごとに利用規約 (`/speaker_info` の policy) を表示し、**確認した話者だけ読み上げに使用可能**（`tts_acknowledged_speakers`）。
- 長い応答は文単位に分割し、ストリーミング中に文が完成した順に合成・再生（初回再生までの待ち時間短縮）。
- 再生は Web Audio。AnalyserNode の音量を口パクに使う。
- **声を作る**: 設定 `tts_custom_voices`（元のスタイル + 高さ `pitchScale`(-0.15〜0.15)・速さ・感情の強さ `intonationScale`・緩急 `tempoDynamicsScale`・音量）を最大20個保存し、`tts_voice` で選ぶ。読み上げの声は「試聴中の調整 → 試聴する元の声 → 作った声 → 元の声」の順で決める（`routers/speech.py: resolve_voice`）。高さを 0 から変えると AivisSpeech の仕様で音質が少し落ちる。
- **声を増やす**（`app/speech/voice_hub.py`）: AivisHub の公開 API（`api.aivis-project.com/v1/aivm-models/search`、`voice_timbres` で種類を絞る）で一覧を取り、AivisSpeech の `/aivm_models/install` にダウンロード URL を渡して AivisSpeech にダウンロードさせる（1つ約240MB）。一覧は設定画面で「声の一覧を開く」を押したときだけ取得し、会話の内容は送らない。試聴はアプリが AivisHub のサンプル音声（`assets.aivis-project.com` のみ）を中継する（CSP を広げないため）。追加・試聴は一覧に出たモデルだけ受け付ける。追加・削除は PC 本体からだけ（`/api/speech/voices` はスマホから使えない）。最後の1つの声は削除できない。追加した声も、使う前に利用規約の確認が必要。

### 7.3 3Dアバター（Three.js + @pixiv/three-vrm）
- VRM は `data/avatars/<id>.vrm` に保存し、メタ情報（名前・作者・ライセンス・クレジット要否）を SQLite `avatars` に保存。
- アップロード時に GLB ヘッダー・JSON チャンク・`VRMC_vrm`(1.0) / `VRM`(0.x) 拡張を検証。ファイル名はサーバーで生成（パス操作不可）。上限 100MB。
- **仮モデル** フラグを持ち、画面に「仮モデル」と常時表示。クレジット表記が必要なモデルはクレジットを表示。
- 動作: まばたき（ランダム間隔）、待機（呼吸・頭の揺れ・腕を下ろす）、口パク（音量→`aa`）、表情（応答文から簡易推定: happy/sad/surprised/relaxed）、リアクション（聞いている/考え中/話している）。
- three.js 一式は遅延読み込み（チャット画面の初期表示を重くしない）。
- VRM 内蔵テクスチャは three.js が `blob:` URL 経由で読み込むため、CSP の `connect-src` に `blob:` を許可（外部ホストは許可しない）。
- `VRMUtils.combineSkeletons` は Seed-san で腕の変形が崩れたため使用しない。
- オリジナルモデル制作手順は [AVATAR.md](AVATAR.md)。

### 7.4 会話状態の共有
- テキストチャットと音声会話は同じ会話（保存設定・会話ID・履歴）を共有する（`ConversationContext`）。

## 8. Phase 4: カレンダー・通知・バックグラウンド

### 8.1 Google Calendar 連携 (`app/calendar/`)
- ライブラリを増やさず httpx で OAuth 2.0（インストール型アプリ + PKCE + ループバック）と Calendar API v3 を直接呼ぶ。
- 権限は **`calendar.events`（予定の読み書き）のみ**。対象は「メインのカレンダー（primary）」。
- OAuth クライアント情報（ユーザーが Google Cloud で作成した「デスクトップアプリ」用 JSON）とトークンは **暗号化して** settings に保存。
- 通信先は `accounts.google.com` / `oauth2.googleapis.com` / `www.googleapis.com` のみ許可（httpx のリクエストフックで強制）。
- リダイレクト先は `http://127.0.0.1:<port>/api/calendar/auth/callback`。`state`（10分で失効）で CSRF を防ぐ。

### 8.2 操作前の確認（承認フロー）
- 予定の追加・変更・削除は、画面のフォームからでも AI の提案からでも、まず **「操作の下書き」(`calendar_operations`, status=pending)** として保存する。
- Google への実行は **`POST /api/calendar/operations/{id}/approve`（画面の承認ボタン）でのみ** 行う。AI はこの API を呼べない（AI の文章で「承認」と言っても実行されない）。
- AI の提案: カレンダー連携中かつ予定に関する発言（キーワード判定）のときだけ、応答後に LLM で JSON の下書きを作り `calendar_proposal` イベントで画面にカードを出す。変更・削除の対象は直近の予定一覧の ID に限定。
- 人格プロンプトにも「承認されるまで実行されない。実行済みと言わない」を追加。

### 8.3 通知 (`app/notify/`)
- バックグラウンドのスケジューラーが 5分ごとに直近の予定をローカルキャッシュ（件名は暗号化）へ同期し、30秒ごとに通知時刻を判定する。
- 通知時刻 = 予定ごとの設定（ローカル）→ なければ既定値（設定画面）。終日予定は当日 8:00。
- **重複防止**: `notifications_sent`（予定ID+開始時刻+分）を SQLite に記録。**再起動後の復元**: キャッシュと送信済み記録が DB に残るので、起動後も同じ判定を続ける。停止中に過ぎた通知は 15 分以内なら遅れて1回だけ出す。
- **PC がシャットダウン・スリープ中は通知できない**（画面に明記）。
- Windows のトースト通知を PowerShell（WinRT API）で表示。件名などは環境変数で渡し、XML はエスケープする（コマンド注入防止）。

### 8.4 バックグラウンドサービス
- サービス = 本アプリのサーバーそのもの（`pythonw -m app.main --background`、コンソールもブラウザーも開かない。ログは `data/logs/server.log`、本文は出力しない）。
- 自動起動: ユーザーのスタートアップフォルダーにショートカット（`PersonalTwinAI.lnk`）を作成/削除。管理者権限不要。
- 停止・再起動: 画面から API で実行（再起動は新しいプロセスがポートの解放を待って起動）。

## 9. Phase 5: 追加学習（LoRA / QLoRA）・蒸留

### 9.1 構成
- 学習は **アプリとは別の venv**（`training/.venv`: PyTorch CUDA 13 / transformers / peft / bitsandbytes）で、`training/train_lora.py` を別プロセスとして実行する。アプリ本体は PyTorch に依存しない。
- 学習用の重みは Hugging Face 形式（`models/hf/<モデル>`）。会話で使うのは Ollama なので、学習した LoRA アダプターを llama.cpp の `convert_lora_to_gguf.py` で GGUF に変換し、`FROM <Ollama の元モデル>` + `ADAPTER` の Modelfile で Ollama に登録する。
- 学習ベースと Ollama 元モデルの組み合わせは固定の一覧で管理（例: `Qwen/Qwen3-1.7B` ↔ `qwen3:1.7b`、`Qwen/Qwen3-8B` ↔ `qwen3:8b`）。

### 9.2 学習データ（記憶種別5: 承認済み学習データ）
- `training_examples`: **保存を許可した会話** の1往復（ユーザー発言→AI応答）からのみ作成。AI 応答は「理想の返答」に修正できる。手動追加・蒸留（教師モデルの回答）も可。
- すべて「承認待ち」で作られ、**承認済みのものだけ** が学習に使われる。本文は暗号化保存。
- 品質検査: 空・短すぎ/長すぎ・正規化後の重複・個人情報らしき文字列（電話番号・メール等）の警告。重複は除去可能。
- エクスポート: 承認済みデータを JSONL（chat 形式）でダウンロード（平文になる旨を確認）。

### 9.3 学習の実行（必ず手動・実行前に確認）
- 実行前の確認画面: ベースモデル・件数・推定時間・GPU メモリ・注意事項を表示し、同意チェック後に開始。
- 学習前バックアップ: 実行ごとのフォルダー `data/training/runs/<id>/` に、使ったデータの暗号化スナップショットと設定を保存（学習中だけ平文の JSONL を作り、終了時に削除）。
- 開始時に Ollama の読み込み済みモデルを解放して GPU メモリを空ける（学習中は会話できない旨を表示）。
- 進捗: 学習プロセスが `status.json`（ステップ・損失・残り時間）を書き、画面が定期取得。ログは `train.log`。中止可能。
- 8GB VRAM の制約: QLoRA（4bit）+ gradient checkpointing + batch 1 + 系列長 1024 を既定。メモリ不足時は失敗として記録し、小型モデルを案内。

### 9.4 評価・切り替え・元に戻す
- 評価: 学習データの 10% を検証用に分け、学習前後の検証損失を比較。固定の評価用質問に対する学習前/後の回答を並べて表示（人が判断）。
- アダプター一覧から「使用する」で `settings.model` を学習済みモデル（`twin-<id>`）に切り替え、「元のモデルに戻す」で切り替え前のモデルに戻す。

### 9.5 蒸留
- 承認済みデータの質問を教師モデル（qwen3:8b）に回答させ、その回答を **承認待ちの学習データ** として追加する（そのまま学習には使わない）。小型モデルを生徒として学習することで、教師の振る舞いを小型モデルへ移す。

## 9A. 自然な会話のための UI（段階A〜D）

- **画面**: 明るい生成り色＋画面ごとの色（`[data-section]` で `--sec-*` を切り替え）。フォント Zen Maru Gothic・アイコン lucide-react は npm で同梱し、外部から読み込まない（CSP `default-src 'self'` のまま。data: URI でのフォント埋め込みは無効化）。
- **おしゃべり画面**（`ChatPage`）: 文字と声を1画面に統合。常にマウントし、非表示中は 3D 描画を止める。表示のたびに設定を読み直す。
- **話し終わりの判定**（`lib/endpointing.ts`）: 最初の 0.3 秒で雑音の大きさを測り、その 2.5 倍（最低 0.06）を声とみなす。声のあと設定の秒数黙ったら終了。
- **読み上げ**: 返事を文ごとに区切り（最初のひと言は読点でも区切る）、音声合成は1件ずつ順番に依頼して先読みする。
- **ふるまい**（`behavior_*`）: うなずき・目線・相づち・文ごとの表情・割り込み。割り込みは読み上げ中もマイクを聞き、厳しめの基準で話しかけを検出したら読み上げと生成を止め、その録音を聞き取りに使う。
- **自分から話しかける**（`services/proactive.py`、`POST /api/proactive/next`）: 画面が1分ごとに確認。きっかけ（予定の前・朝・しばらく話していない）と話しかけない時間帯をサーバーで判定し、人格プロンプト＋アプリからの指示で短い声かけを作る。記録はキーだけ（`notifications_sent` の `proactive:*`）。
- **「ねえ○○」で起きる**（`state/useWakeWord.ts`、`lib/wakeMatch.ts`、`/api/wake`）: 「あなたのこと」（`self.*` のプロフィール3項目＋AI の名前）がそろい、同意（`consents.kind = wake_word`）した場合だけ有効。短い発話を `stt?fast=true` で文字にして、カタカナ→ひらがな等を正規化して名前（と読み）を照合。音声は保存・送信しない。待ち受け中は常に表示する。
- **言語**（`language`）: Whisper の言語と人格プロンプトの言語を切り替える。読み上げは日本語のみ。
- **PWA**: `manifest.webmanifest`、`sw.js`（`/assets/` はキャッシュ優先、画面本体はネットワーク優先、`/api/` は対象外）。

## 9B. 景色・天気（アバターの「いまいる場所」）

- **画面**: おしゃべり画面は景色（`components/scene/SceneBackdrop.tsx`）の上にアバターを大きく置き、会話は左下に背景なしの文字で重ねる（スマホ幅では下に全幅）。
- **場所の決め方**（`services/scene.py`、`GET /api/scene`）: `scene_mode=auto` では、夜（20時〜）・朝（〜9時）・雨/雪/雷の日は家。昼間は日付と2時間ごとの区切りから決まる同じ選び方で、公園・街・カフェ・家・自分で追加した出かけ先を回る（開くたびに変わらない）。固定（`room` 等、`custom:<id>`）も選べる。
- **見た目**（`lib/sceneLook.ts`）: 時間帯（明け方・昼・夕方・夜）で空の色と景色全体の色を変え、夕方・夜は街灯や部屋の明かりをつける。雨・雪・霧・雷を重ねる（屋内は窓の外だけ）。景色は SVG で描き、少しぼかしてアバターを引き立てる。
- **天気**（`services/weather.py`）: 設定でオンにしたときだけ Open-Meteo（無料・登録不要）に、選んだ場所の緯度・経度だけを送る。30分ためておく。場所は地名で検索して選ぶ（`/api/weather/places`、`/api/weather/place`）。取得に失敗しても天気なしで場所を決める。
- **AI への伝え方**: 「いまのようす」（居場所と天気予報）を人格プロンプトに入れる。天気予報があるときだけ、天気を聞かれたら答えてよいとし、それ以外のリアルタイム情報は分からないと伝える。
- **自分で用意した背景**（`app/backgrounds.py`、`/api/backgrounds`）: PNG/JPEG/WebP（15MBまで、先頭のバイトで確認）を `data/backgrounds/` に保存。種類は家・出かけ先（屋内）・出かけ先（屋外）。

## 9C. スマホから使う（Tailscale 経由）

- サーバーは今までどおり `127.0.0.1` だけで待ち受ける。`tailscale serve --bg --https=443 http://127.0.0.1:8765` で、自分の Tailscale ネットワーク（同じアカウントの機器だけ）からの https 接続を中継する。インターネットには公開しない（Funnel は使わない）。証明書は Tailscale が発行する正式なもの（スマホでもマイクが使える）。
- Host 検証（`HostCheckMiddleware`）は、オンにしたときだけ Tailscale の名前（`*.ts.net`）を許可する。送信元の確認も同じ名前の https だけを追加で許可する。
- Tailscale の名前からの API は、ペアリングした端末だけ（`RemoteGateMiddleware`）。ペアリングは PC 本体で出した6桁の合言葉（10分・1回限り・5回まちがえたら無効）で行い、端末には `secrets.token_urlsafe(32)` のトークンを HttpOnly・Secure・SameSite=Strict の Cookie で渡す。サーバーには SHA-256 だけを `remote_devices.json` に保存する。画面のファイル（個人データを含まない）と `/api/health`・`/api/remote/pair`・`/api/remote/me` は誰でも読める。
- PC 本体だけでできる操作: `/api/system`（停止・再起動・自動起動）、`/api/remote`（オン・オフ・合言葉・端末の解除）、`/api/data`（書き出し・読み込み）。
- オン・オフと名前は設定（`remote_enabled` / `remote_host`）に残し、再起動後も受け付ける（中継の設定は Tailscale 側に残る）。

## 10. 技術的な確認事項・リスク

- **Python 3.14**: Phase 1 依存と ChromaDB 1.5.9 / cryptography 50 は動作確認済み。faster-whisper / PEFT 系は Phase 3/5 開始時に確認し、未対応なら Python 3.12 の venv を使う。
- **Qwen3 思考モード**: Ollama の `think` パラメーターで制御（既定オフ、設定で切替）。旧形式の `<think>` タグが本文に混入した場合も除去する。
- **8GB VRAM**: qwen3:8b (Q4_K_M) + ctx 4096 で約5.6GB。Phase 3 で音声処理を同時に動かす場合、faster-whisper は CPU (int8) を既定にする。
- **QLoRA (Phase 5)**: 8B の QLoRA は 8GB では厳しい可能性が高い。まず Qwen3 1.7B/4B で検証する。
- **暗号化の限界**: DPAPI は同じ Windows ユーザーでログインできる攻撃者からは守れない。ChromaDB のベクトルは平文（埋め込みから元文を推定する攻撃の可能性がある）。
