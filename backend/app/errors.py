"""ユーザー向け日本語エラー。レスポンスは {"detail": {"code", "message"}} 形式に統一する。"""

from __future__ import annotations

from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code
        self.message = message


def setup_required() -> AppError:
    return AppError(409, "setup_required", "初回設定が完了していません。初回設定画面から設定してください。")
