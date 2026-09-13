"""256 KB request-body cap as pure ASGI middleware (02: bodies > 256 KB -> 413).

Pure ASGI rather than ``@app.middleware("http")``: the decorator form wraps
responses in Starlette's BaseHTTPMiddleware, which is unsuitable for the
long-lived streaming responses this service now serves (SSE, ragproxy). The
cap is checked against ``Content-Length`` up front and against the bytes
actually received, so a chunked upload cannot slip past it. After the body
is replayed, ``receive`` passes through, so disconnect detection on
streaming responses still works.
"""

from __future__ import annotations

import json

MAX_BODY_BYTES = 256 * 1024

_BODY = json.dumps({"detail": "request body exceeds the 256 KB limit"}).encode()


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > self.max_bytes:
                        await _reject(send)
                        return
                except ValueError:
                    pass
        # Read the (bounded) body before the app runs. Raising from inside
        # `receive` instead would be swallowed by FastAPI's body parser and
        # surface as a 400; buffering at most 256 KB is cheap and exact.
        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # Client went away before sending the body.
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_bytes:
                await _reject(send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks),
                        "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _reject(send) -> None:
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(_BODY)).encode())]})
    await send({"type": "http.response.body", "body": _BODY})
