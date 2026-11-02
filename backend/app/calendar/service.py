"""Google カレンダー連携の本体。

- クライアント情報とトークンは暗号化して保存する。
- 予定の追加・変更・削除は「操作の下書き」を作り、承認 API が呼ばれたときだけ Google に送る。
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from app.calendar.google import ClientConfig, GoogleAuthError, GoogleClient, GoogleError, Token, new_pkce
from app.calendar.models import CalendarEvent, EventDraft, Operation, OperationCreate, local_now
from app.crypto import Vault
from app.db import Database, now_iso
from app.repositories.settings import SettingsRepository

logger = logging.getLogger(__name__)

CLIENT_KEY = "google_client"
TOKEN_KEY = "google_token"
STATE_TTL_SECONDS = 600
CACHE_DAYS = 3


class CalendarError(Exception):
    def __init__(self, message: str, code: str = "calendar_error", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def not_connected() -> CalendarError:
    return CalendarError("Google カレンダーと連携していません。カレンダー画面から連携してください。", "calendar_not_connected", 409)


class CalendarService:
    def __init__(self, db: Database, vault: Vault, settings: SettingsRepository, google: GoogleClient) -> None:
        self.db = db
        self.vault = vault
        self.settings = settings
        self.google = google
        # state -> (PKCE verifier, redirect_uri, 作成時刻)。メモリ上のみ（再起動で無効になる）
        self._pending: dict[str, tuple[str, str, float]] = {}

    # ---------- 認証情報 ----------

    def _load_secret(self, key: str) -> str | None:
        raw = self.settings.get_raw(key)
        return self.vault.decrypt(raw) if raw else None

    def _save_secret(self, key: str, value: str | None) -> None:
        self.settings.set_raw(key, self.vault.encrypt(value) if value is not None else None)

    def client(self) -> ClientConfig | None:
        raw = self._load_secret(CLIENT_KEY)
        return ClientConfig(**json.loads(raw)) if raw else None

    def save_client(self, config: ClientConfig) -> None:
        self._save_secret(CLIENT_KEY, json.dumps({"client_id": config.client_id, "client_secret": config.client_secret}))
        # クライアントを変えたら以前のトークンは使えない
        self._save_secret(TOKEN_KEY, None)

    def _token(self) -> Token | None:
        raw = self._load_secret(TOKEN_KEY)
        return Token.from_json(raw) if raw else None

    def status(self) -> dict[str, Any]:
        client = self.client()
        return {
            "configured": client is not None,
            # クライアントIDの先頭だけ表示する（どのクライアントか確認できる程度）
            "client_id_hint": (client.client_id[:12] + "…") if client else None,
            "connected": self._token() is not None,
        }

    # ---------- OAuth ----------

    def start_auth(self, redirect_uri: str) -> str:
        client = self.client()
        if client is None:
            raise CalendarError("先に OAuth クライアントの JSON を登録してください。", "calendar_not_configured", 409)
        now = time.time()
        self._pending = {s: v for s, v in self._pending.items() if now - v[2] < STATE_TTL_SECONDS}
        state = secrets.token_urlsafe(24)
        verifier, challenge = new_pkce()
        self._pending[state] = (verifier, redirect_uri, now)
        return self.google.auth_url(client, redirect_uri, state, challenge)

    async def finish_auth(self, state: str, code: str) -> None:
        entry = self._pending.pop(state, None)
        if entry is None or time.time() - entry[2] > STATE_TTL_SECONDS:
            raise CalendarError("連携の有効期限が切れたか、不正な要求です。もう一度「Google と連携」を押してください。", "invalid_state")
        client = self.client()
        if client is None:
            raise CalendarError("OAuth クライアントが登録されていません。", "calendar_not_configured", 409)
        verifier, redirect_uri, _ = entry
        token = await self.google.exchange_code(client, code, verifier, redirect_uri)
        self._save_secret(TOKEN_KEY, token.to_json())

    async def disconnect(self) -> None:
        token = self._token()
        if token:
            await self.google.revoke(token)
        self._save_secret(TOKEN_KEY, None)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM calendar_cache")

    async def _access_token(self) -> str:
        client, token = self.client(), self._token()
        if client is None or token is None:
            raise not_connected()
        if token.expired():
            try:
                token = await self.google.refresh(client, token)
            except GoogleAuthError:
                # 取り消されたトークンは削除して、連携し直してもらう
                self._save_secret(TOKEN_KEY, None)
                raise
            self._save_secret(TOKEN_KEY, token.to_json())
        return token.access_token

    async def _api(self, method: str, path: str, **kwargs: Any) -> Any:
        access = await self._access_token()
        try:
            return await self.google.api(method, path, access, **kwargs)
        except GoogleAuthError:
            self._save_secret(TOKEN_KEY, None)
            raise

    # ---------- 予定 ----------

    async def list_events(self, start: datetime, end: datetime, limit: int = 250) -> list[CalendarEvent]:
        data = await self._api(
            "GET",
            "/events",
            params={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": str(limit),
            },
        )
        events = [CalendarEvent.from_google(item) for item in (data or {}).get("items", []) if item.get("status") != "cancelled"]
        overrides = self.notify_overrides()
        return [e.model_copy(update={"notify_minutes": overrides.get(e.id)}) for e in events]

    async def get_event(self, event_id: str) -> CalendarEvent:
        return CalendarEvent.from_google(await self._api("GET", f"/events/{event_id}"))

    async def upcoming(self, days: int = 7) -> list[CalendarEvent]:
        now = local_now()
        return await self.list_events(now - timedelta(hours=1), now + timedelta(days=days))

    # ---------- 操作の下書きと承認 ----------

    async def propose(self, body: OperationCreate, source: str) -> Operation:
        target = None
        if body.action in ("update", "delete"):
            # 対象が実在することを確認し、確認画面に操作前の内容を表示する
            target = await self.get_event(body.event_id or "")
        op_id = uuid.uuid4().hex
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO calendar_operations (id, action, event_id, draft, target, source, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    op_id,
                    body.action,
                    body.event_id,
                    self.vault.encrypt(body.draft.model_dump_json()) if body.draft else None,
                    self.vault.encrypt(target.model_dump_json()) if target else None,
                    source,
                    now_iso(),
                ),
            )
        op = self.get_operation(op_id)
        assert op is not None
        return op

    def get_operation(self, op_id: str) -> Operation | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM calendar_operations WHERE id = ?", (op_id,)).fetchone()
        return self._to_operation(row) if row else None

    def list_operations(self, status: str | None = "pending") -> list[Operation]:
        sql, params = "SELECT * FROM calendar_operations", ()
        if status:
            sql, params = sql + " WHERE status = ?", (status,)
        with self.db.transaction() as conn:
            rows = conn.execute(sql + " ORDER BY created_at DESC, rowid DESC LIMIT 50", params).fetchall()
        return [self._to_operation(r) for r in rows]

    def _decide(self, op_id: str, status: str, error: str | None = None, result_event_id: str | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE calendar_operations SET status = ?, error = ?, result_event_id = ?, decided_at = ? WHERE id = ?",
                (status, error, result_event_id, now_iso(), op_id),
            )

    def _claim(self, op_id: str) -> Operation:
        """承認待ちの操作を「処理中」にする。二重に承認されても1回だけ実行する。"""
        with self.db.transaction() as conn:
            claimed = conn.execute(
                "UPDATE calendar_operations SET status = 'running' WHERE id = ? AND status = 'pending'", (op_id,)
            ).rowcount
        op = self.get_operation(op_id)
        if op is None:
            raise CalendarError("指定された操作が見つかりません。", "operation_not_found", 404)
        if not claimed:
            raise CalendarError("この操作はすでに処理済みです。", "operation_not_pending", 409)
        return op

    async def approve(self, op_id: str) -> Operation:
        """ユーザーが画面で承認したときだけ呼ばれる。ここで初めて Google に送信する。"""
        op = self._claim(op_id)
        try:
            result_id: str | None = None
            if op.action == "create" and op.draft:
                created = await self._api("POST", "/events", json=op.draft.to_google())
                result_id = str(created["id"])
            elif op.action == "update" and op.draft:
                updated = await self._api("PATCH", f"/events/{op.event_id}", json=op.draft.to_google())
                result_id = str(updated["id"])
            elif op.action == "delete":
                await self._api("DELETE", f"/events/{op.event_id}")
                result_id = op.event_id
                with self.db.transaction() as conn:
                    conn.execute("DELETE FROM calendar_cache WHERE event_id = ?", (op.event_id,))
            self._decide(op_id, "done", result_event_id=result_id)
        except (GoogleError, CalendarError) as exc:
            self._decide(op_id, "failed", error=exc.message)
            raise
        if op.draft and op.draft.reminder_minutes is not None and result_id:
            self.set_notify(result_id, op.draft.reminder_minutes)
        result = self.get_operation(op_id)
        assert result is not None
        return result

    def reject(self, op_id: str) -> Operation:
        op = self.get_operation(op_id)
        if op is None:
            raise CalendarError("指定された操作が見つかりません。", "operation_not_found", 404)
        if op.status != "pending":
            raise CalendarError("この操作はすでに処理済みです。", "operation_not_pending", 409)
        self._decide(op_id, "rejected")
        result = self.get_operation(op_id)
        assert result is not None
        return result

    def _to_operation(self, row: Any) -> Operation:
        data = dict(row)
        draft = data.pop("draft")
        target = data.pop("target")
        status = data["status"]
        return Operation(
            **{**data, "status": "pending" if status == "running" else status},
            draft=EventDraft.model_validate_json(self.vault.decrypt(draft)) if draft else None,
            target=CalendarEvent.model_validate_json(self.vault.decrypt(target)) if target else None,
        )

    # ---------- 通知用の設定とキャッシュ ----------

    def notify_overrides(self) -> dict[str, int]:
        with self.db.transaction() as conn:
            return {r["event_id"]: r["minutes"] for r in conn.execute("SELECT event_id, minutes FROM event_notify")}

    def set_notify(self, event_id: str, minutes: int | None) -> None:
        with self.db.transaction() as conn:
            if minutes is None:
                conn.execute("DELETE FROM event_notify WHERE event_id = ?", (event_id,))
            else:
                conn.execute(
                    "INSERT INTO event_notify (event_id, minutes, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(event_id) DO UPDATE SET minutes = excluded.minutes, updated_at = excluded.updated_at",
                    (event_id, minutes, now_iso()),
                )

    async def sync_cache(self) -> int:
        """通知のために直近の予定をローカルに保存する（件名などは暗号化）。"""
        now = local_now()
        events = await self.list_events(now - timedelta(days=1), now + timedelta(days=CACHE_DAYS))
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM calendar_cache")
            conn.executemany(
                "INSERT INTO calendar_cache (event_id, event, starts_at, synced_at) VALUES (?, ?, ?, ?)",
                [(e.id, self.vault.encrypt(e.model_dump_json()), e.start_dt().isoformat(), ts) for e in events],
            )
        return len(events)

    def cached_events(self) -> list[CalendarEvent]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT event FROM calendar_cache ORDER BY starts_at").fetchall()
        return [CalendarEvent.model_validate_json(self.vault.decrypt(r["event"])) for r in rows]

    def is_connected(self) -> bool:
        return self._token() is not None and self.client() is not None
