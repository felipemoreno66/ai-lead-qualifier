"""Per-workspace CORS for ``/api/*``.

The allowed origins of a request are the workspace's ``cors.allowed_origins`` plus the web
app origin(s) from ``WEB_PUBLIC_ORIGIN``. Never ``*``, never credentials. CORS only guards
browsers, so intake is additionally rate limited for every caller.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lead_qualifier.workspaces.loader import WorkspaceRegistry

SLUG_PATH = re.compile(r"^/api/(?:leads|workspaces)/([a-z0-9-]+)(?:/|$)")
ALLOW_METHODS = "GET, POST, OPTIONS"
ALLOW_HEADERS = "content-type"
MAX_AGE = "600"


class WorkspaceCORSMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        registry: WorkspaceRegistry,
        web_origins: Iterable[str],
        allow_draft: bool,
    ) -> None:
        self.app = app
        self.registry = registry
        self.web_origins = frozenset(o.rstrip("/") for o in web_origins if o)
        self.allow_draft = allow_draft

    def allowed_origins(self, slug: str) -> frozenset[str] | None:
        workspace = self.registry.public(slug, allow_draft=self.allow_draft)
        if workspace is None:
            return None
        return self.web_origins | frozenset(workspace.config.cors.allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        match = SLUG_PATH.match(scope["path"])
        allowed = self.allowed_origins(match.group(1)) if match else None
        if origin is None or allowed is None:
            await self.app(scope, receive, send)
            return

        is_allowed = origin in allowed
        method = scope["method"]

        if method == "OPTIONS" and headers.get("access-control-request-method"):
            if not is_allowed:
                await self._forbidden(scope, receive, send, origin)
                return
            response = JSONResponse(None, status_code=204)
            self._add_headers(response.headers, origin, preflight=True)
            await response(scope, receive, send)
            return

        if method == "POST" and not is_allowed:
            await self._forbidden(scope, receive, send, origin)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start" and is_allowed:
                self._add_headers(MutableHeaders(scope=message), origin, preflight=False)
            await send(message)

        await self.app(scope, receive, send_with_cors)

    @staticmethod
    def _add_headers(headers: MutableHeaders, origin: str, *, preflight: bool) -> None:
        headers["access-control-allow-origin"] = origin
        headers.append("vary", "Origin")
        if preflight:
            headers["access-control-allow-methods"] = ALLOW_METHODS
            headers["access-control-allow-headers"] = ALLOW_HEADERS
            headers["access-control-max-age"] = MAX_AGE

    @staticmethod
    async def _forbidden(scope: Scope, receive: Receive, send: Send, origin: str) -> None:
        request_id = scope.get("state", {}).get("request_id")
        response = JSONResponse(
            {
                "type": "about:blank",
                "title": "Forbidden",
                "status": 403,
                "detail": "This origin is not allowed to call this workspace.",
                "request_id": request_id,
            },
            status_code=403,
            media_type="application/problem+json",
            headers={"vary": "Origin"},
        )
        await response(scope, receive, send)
