"""ローカルサーバーへの不正アクセス対策。

- Host ヘッダー検証は main.py で TrustedHostMiddleware を使う（DNS リバインディング対策）。
- ここでは状態変更リクエストの Origin 検証（他サイトからの CSRF 対策）とセキュリティヘッダーを扱う。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: tuple[str, ...]) -> None:  # noqa: ANN001
        super().__init__(app)
        self.allowed_origins = frozenset(allowed_origins)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            # ブラウザーからのクロスオリジン要求は必ず Origin が付く。付いていない場合は
            # ブラウザー外（curl 等）からの要求で、Host 検証により localhost 限定になっている。
            if origin is not None and origin not in self.allowed_origins:
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
