"""ragproxy — ADR-V02. A transparent forward from VSS's frag tool to the RAG
server that makes retrieval observable.

``RAG_SERVER_URL`` for the VSS agent is ``http://mock-wo:8090/ragproxy/v1``;
requests are forwarded verbatim to ``<RAG_UPSTREAM_URL>/v1/...``.

Rules (ADR-V02 consequences, tested):

- **Observer, never participant.** Request and response bodies are forwarded
  byte for byte. Only hop-by-hop headers are dropped, and ``Accept-Encoding``
  so the upstream answers in identity encoding and the observer can read
  what it forwards without re-encoding anything.
- **No buffering.** Response chunks are relayed as they arrive, so a
  streaming ``/v1/generate`` stays a stream.
- **Failures pass through.** Upstream 4xx/5xx reach the caller unchanged.
  Only an unreachable upstream, where there is nothing to pass through,
  becomes a 502 from the proxy.
- **The ``/v1`` suffix stays load-bearing**: only ``/ragproxy/v1/*`` exists.

Each POST emits ``retrieval.query`` before forwarding and
``retrieval.result`` after the response completes, attached to the incident
in flight. Event emission can never break a forward.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .ops import Operations

log = logging.getLogger("mock-wo.ragproxy")

HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length",
})
DROP_REQUEST = HOP_BY_HOP | {"accept-encoding"}
OBSERVE_LIMIT = 1024 * 1024
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def query_text(body: bytes) -> Optional[str]:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("query", "question", "input"):
        if isinstance(data.get(key), str):
            return data[key][:1000]
    messages = data.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    return content[:1000]
    return None


def result_documents(body: bytes) -> List[Dict[str, Any]]:
    """Best-effort document list from a RAG search or generate response.
    Handles a JSON body and an SSE body (``data:`` lines)."""
    candidates: List[Any] = []
    text = body.decode("utf-8", errors="replace")
    try:
        candidates.append(json.loads(text))
    except ValueError:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    candidates.append(json.loads(line[5:].strip()))
                except ValueError:
                    continue
    documents: List[Dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        for result in _results(candidate):
            name = (result.get("document_name") or result.get("source")
                    or result.get("document_id") or "")
            snippet = result.get("content") or result.get("text") or ""
            key = (name, snippet[:80])
            if key in seen:
                continue
            seen.add(key)
            documents.append({
                "document_name": str(name)[:200],
                "score": result.get("score"),
                "snippet": str(snippet)[:300],
            })
    return documents[:20]


def _results(candidate: Any) -> List[Dict[str, Any]]:
    if not isinstance(candidate, dict):
        return []
    found: List[Dict[str, Any]] = []
    for key in ("results",):
        if isinstance(candidate.get(key), list):
            found.extend(r for r in candidate[key] if isinstance(r, dict))
    citations = candidate.get("citations")
    if isinstance(citations, dict) and isinstance(citations.get("results"), list):
        found.extend(r for r in citations["results"] if isinstance(r, dict))
    return found


def create_router(ops: Operations) -> APIRouter:
    router = APIRouter()
    state: Dict[str, Optional[httpx.AsyncClient]] = {"client": None}

    def client() -> httpx.AsyncClient:
        if state["client"] is None:
            state["client"] = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=600.0, write=60.0,
                                      pool=10.0),
                transport=ops.core.rag_transport,
            )
        return state["client"]

    async def emit(event_type: str, data: Dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(ops.retrieval_event, event_type, data)
        except Exception:  # pragma: no cover - observation must never break a forward
            log.exception("ragproxy: failed to record %s", event_type)

    @router.api_route("/ragproxy/v1/{path:path}", methods=METHODS)
    async def forward(path: str, request: Request):
        upstream = ops.core.settings.rag_upstream.rstrip("/") + "/v1/" + path
        body = await request.body()
        headers = [(k, v) for k, v in request.headers.items()
                   if k.lower() not in DROP_REQUEST]
        observe = request.method == "POST"
        started = time.monotonic()
        if observe:
            await emit("retrieval.query", {"path": "/v1/" + path,
                                           "query": query_text(body)})
        try:
            upstream_request = client().build_request(
                request.method, upstream, params=request.query_params,
                headers=headers, content=body)
            response = await client().send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            if observe:
                await emit("retrieval.result", {
                    "path": "/v1/" + path, "status": 502, "documents": [],
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "error": f"upstream unreachable: {type(exc).__name__}"})
            return JSONResponse(status_code=502, content={
                "detail": f"ragproxy: RAG upstream unreachable ({type(exc).__name__})"})

        async def relay():
            captured = bytearray()
            try:
                async for chunk in response.aiter_raw():
                    if observe and len(captured) < OBSERVE_LIMIT:
                        captured.extend(chunk[:OBSERVE_LIMIT - len(captured)])
                    yield chunk
            finally:
                await response.aclose()
                if observe:
                    await emit("retrieval.result", {
                        "path": "/v1/" + path, "status": response.status_code,
                        "documents": result_documents(bytes(captured)),
                        "latency_ms": round((time.monotonic() - started) * 1000)})

        out_headers = {k: v for k, v in response.headers.items()
                       if k.lower() not in HOP_BY_HOP}
        return StreamingResponse(relay(), status_code=response.status_code,
                                 headers=out_headers)

    async def close() -> None:
        if state["client"] is not None:
            await state["client"].aclose()
            state["client"] = None

    router.close_client = close  # type: ignore[attr-defined]
    return router
