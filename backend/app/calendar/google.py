"""Google OAuth 2.0（インストール型アプリ + PKCE）と Calendar API v3 の最小クライアント。

外部通信先は Google の3ホストに限定する（それ以外への送信はリクエスト前に拒否）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/primary"
# 予定の読み書きだけを許可する最小の権限
SCOPE = "https://www.googleapis.com/auth/calendar.events"
ALLOWED_HOSTS = frozenset({"accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com"})


class GoogleError(Exception):
    """ユーザーに表示できる日本語メッセージを持つ例外。"""

    def __init__(self, message: str, code: str = "google_error", status: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class GoogleAuthError(GoogleError):
    def __init__(self, message: str = "Google の認証が切れました。カレンダー画面から連携し直してください。") -> None:
        super().__init__(message, "google_auth_required", 401)


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    client_secret: str


@dataclass
class Token:
    access_token: str
    refresh_token: str
    expires_at: float
    scope: str

    def expired(self, margin: float = 60.0) -> bool:
        return time.time() + margin >= self.expires_at

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> Token:
        return cls(**json.loads(raw))


def parse_client_json(data: bytes) -> ClientConfig:
    """Google Cloud でダウンロードした OAuth クライアントの JSON を読む。"""
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise GoogleError("JSON ファイルとして読み込めませんでした。", "invalid_client", 400) from exc
    if not isinstance(parsed, dict):
        raise GoogleError("OAuth クライアントの JSON ではありません。", "invalid_client", 400)
    if "web" in parsed:
        raise GoogleError(
            "「ウェブアプリケーション」用のクライアントです。種類「デスクトップアプリ」で作成し直してください。",
            "invalid_client",
            400,
        )
    installed = parsed.get("installed")
    if not isinstance(installed, dict) or not installed.get("client_id") or not installed.get("client_secret"):
        raise GoogleError(
            "デスクトップアプリ用の OAuth クライアントの JSON ではありません。", "invalid_client", 400
        )
    return ClientConfig(str(installed["client_id"]), str(installed["client_secret"]))


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def _only_google(request: httpx.Request) -> None:
    if request.url.host not in ALLOWED_HOSTS:
        raise GoogleError("許可されていない通信先です。", "forbidden_host", 500)


class GoogleClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), transport=transport, follow_redirects=False,
            event_hooks={"request": [_only_google]},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def auth_url(client: ClientConfig, redirect_uri: str, state: str, code_challenge: str) -> str:
        params = {
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            # refresh_token を確実に受け取る
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self._http.post(TOKEN_URL, data=data)
        except httpx.TransportError as exc:
            raise GoogleError("Google に接続できません。インターネット接続を確認してください。", "google_unreachable") from exc
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code != 200:
            if body.get("error") in {"invalid_grant", "unauthorized_client"}:
                raise GoogleAuthError()
            raise GoogleError("Google の認証に失敗しました。クライアント情報を確認してください。", "google_token_failed", 400)
        return body

    async def exchange_code(self, client: ClientConfig, code: str, verifier: str, redirect_uri: str) -> Token:
        body = await self._token_request(
            {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )
        if not body.get("refresh_token"):
            raise GoogleError("Google から更新用トークンを受け取れませんでした。連携し直してください。", "no_refresh_token", 400)
        scope = str(body.get("scope", ""))
        if SCOPE not in scope.split():
            raise GoogleError("カレンダーへのアクセスが許可されませんでした。同意画面でチェックを入れてください。", "scope_denied", 400)
        return Token(str(body["access_token"]), str(body["refresh_token"]), time.time() + int(body.get("expires_in", 3600)), scope)

    async def refresh(self, client: ClientConfig, token: Token) -> Token:
        body = await self._token_request(
            {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "refresh_token": token.refresh_token,
                "grant_type": "refresh_token",
            }
        )
        return Token(
            str(body["access_token"]), token.refresh_token, time.time() + int(body.get("expires_in", 3600)),
            str(body.get("scope", token.scope)),
        )

    async def revoke(self, token: Token) -> None:
        try:
            await self._http.post(REVOKE_URL, data={"token": token.refresh_token})
        except httpx.TransportError:
            pass  # 連携解除はローカルのトークン削除を優先する

    async def api(self, method: str, path: str, access_token: str, **kwargs: Any) -> Any:
        try:
            response = await self._http.request(
                method, f"{CALENDAR_API}{path}", headers={"Authorization": f"Bearer {access_token}"}, **kwargs
            )
        except httpx.TransportError as exc:
            raise GoogleError("Google カレンダーに接続できません。インターネット接続を確認してください。", "google_unreachable") from exc
        if response.status_code == 401:
            raise GoogleAuthError()
        if response.status_code == 404 or response.status_code == 410:
            raise GoogleError("予定が見つかりません。すでに削除された可能性があります。", "event_not_found", 404)
        if response.status_code == 403:
            raise GoogleError(
                "Google カレンダーへのアクセスが拒否されました。Calendar API が有効か確認してください。", "google_forbidden", 403
            )
        if response.status_code >= 400:
            raise GoogleError("Google カレンダーの操作に失敗しました。", "google_api_error", 502)
        return response.json() if response.content else None
