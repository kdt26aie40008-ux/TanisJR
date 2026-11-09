"""ローカルサーバーへの不正アクセス対策。

- Host ヘッダー検証は main.py で TrustedHostMiddleware を使う（DNS リバインディング対策）。
- ここでは状態変更リクエストの Origin 検証（他サイトからの CSRF 対策）とセキュリティヘッダーを扱う。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from app.remote import COOKIE_NAME, RemoteAccess

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        # blob: は VRM 内蔵テクスチャの読み込み（three.js がページ内で作る Blob URL）に必要。外部通信は許可しない
        "connect-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    ]
)


def _hostname(request: Request) -> str:
    host = request.headers.get("host", "")
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def is_remote(request: Request, remote: RemoteAccess | None) -> bool:
    """スマホなど、Tailscale 経由（PC 本体以外）からの接続か。"""
    return bool(remote and remote.host and _hostname(request) == remote.host)


class HostCheckMiddleware(BaseHTTPMiddleware):
    """Host ヘッダー検証（DNS リバインディング対策）。

    PC 本体の名前に加えて、「スマホから使う」をオンにしたときだけ Tailscale の名前を許可する。
    """

    def __init__(self, app, allowed_hosts: tuple[str, ...], remote: RemoteAccess | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self.allowed_hosts = frozenset(allowed_hosts)
        self.remote = remote

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        name = _hostname(request)
        if name not in self.allowed_hosts and not is_remote(request, self.remote):
            return PlainTextResponse("Invalid host header", status_code=400)
        return await call_next(request)


# スマホから使うとき、ペアリングしていなくても使える API（状態の確認とペアリングだけ）
_REMOTE_OPEN = frozenset({"/api/health", "/api/remote/pair", "/api/remote/me"})
# PC 本体からだけできる操作（サーバーの停止、スマホの登録・解除、データの書き出し・読み込み）
_LOCAL_ONLY = ("/api/system", "/api/remote", "/api/data")


class RemoteGateMiddleware(BaseHTTPMiddleware):
    """Tailscale 経由の接続は、ペアリングした端末だけに API を使わせる。画面のファイルは誰でも読める（個人データを含まない）。"""

    def __init__(self, app, remote: RemoteAccess) -> None:  # noqa: ANN001
        super().__init__(app)
        self.remote = remote

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if is_remote(request, self.remote) and path.startswith("/api/") and path not in _REMOTE_OPEN:
            if path.startswith(_LOCAL_ONLY):
                return JSONResponse(
                    status_code=403,
                    content={"detail": {"code": "local_only", "message": "この操作は PC 本体からだけできます。"}},
                )
            if not self.remote.check(request.cookies.get(COOKIE_NAME)):
                return JSONResponse(
                    status_code=401,
                    content={"detail": {"code": "pairing_required", "message": "このスマホはまだつながっていません。PC で表示した合言葉を入れてください。"}},
                )
        return await call_next(request)


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: tuple[str, ...], remote: RemoteAccess | None = None) -> None:  # noqa: ANN001
        super().__init__(app)
        self.allowed_origins = frozenset(allowed_origins)
        self.remote = remote

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            allowed = self.allowed_origins
            if self.remote and self.remote.host:
                allowed = allowed | {f"https://{self.remote.host}"}
            # ブラウザーからのクロスオリジン要求は必ず Origin が付く。付いていない場合は
            # ブラウザー外（curl 等）からの要求で、Host 検証により localhost 限定になっている。
            if origin is not None and origin not in allowed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": {"code": "forbidden_origin", "message": "許可されていない送信元からのリクエストです。"}},
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response
