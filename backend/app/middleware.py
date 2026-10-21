"""Pure ASGI middleware, so streaming responses added later are not buffered."""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("app.request")
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


class RequestIdMiddleware:
    """Adds an X-Request-ID header and logs one line per request (never the body)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = _SAFE_ID.sub("", incoming)[:64] or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log.info(
                "%s %s -> %s in %dms rid=%s",
                scope["method"],
                scope["path"],
                status,
                int((time.perf_counter() - start) * 1000),
                request_id,
            )
