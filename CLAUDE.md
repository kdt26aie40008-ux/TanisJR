# CLAUDE.md

AnotherMe（もう一人の私。旧称: 第二の自分AI / Personal Twin AI）。作業前に必ず読むこと:

- 設計方針: `docs/ARCHITECTURE.md`
- 進捗・未完了タスク・既知の問題: `docs/PROGRESS.md`（作業後に更新する）

## ルール

- フェーズ単位で進め、フェーズ完了時は報告してユーザーの指示を待つ。
- 初回3問の文言・順序（`backend/app/setup_questions.py`）は変更禁止。
- 会話本文・個人情報をログに出力しない。保存許可のない会話を永続化しない。
- 未実装機能は「準備中（Phase N）」と明示し、動くように見せかけない。未検証の機能は未検証と報告する。
- 秘密情報・`data/` をコミットしない。

## コマンド

- テスト: `cd backend; .\.venv\Scripts\python -m pytest` / `cd frontend; npm test`
- ビルド: `cd frontend; npm run build`
- 起動: `.\scripts\start.ps1`（http://127.0.0.1:8765）
- git は `D:` の所有者問題で `git -c safe.directory=D:/TanisJr ...` が必要な場合がある
