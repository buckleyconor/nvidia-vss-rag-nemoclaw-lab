"""M3 — ragproxy (ADR-V02): verbatim forward, no buffering, failures pass
through, retrieval events, `/v1` suffix load-bearing."""

import asyncio
import json

import httpx
import pytest

from app import apps, ragproxy
from conftest import inject

SEARCH_RESPONSE = {
    "total_results": 2,
    "results": [
        {"document_name": "manual-01.md", "content": "Bearing temperature above 75 °C",
         "score": 0.91},
        {"document_name": "log-01.md", "content": "Bearing housing 71 °C", "score": 0.72},
    ],
}


class Upstream:
    def __init__(self):
        self.requests = []
        self.status = 200
        self.body = json.dumps(SEARCH_RESPONSE).encode()
        self.headers = {"content-type": "application/json", "x-rag-trace": "t-1"}
        self.raise_error = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.raise_error:
            raise self.raise_error
        self.requests.append(request)
        body = self.body

        async def stream():
            # A real upstream streams; a bytes body would arrive pre-read.
            yield body

        return httpx.Response(self.status, content=stream(), headers=self.headers)


@pytest.fixture()
def upstream(core):
    fake = Upstream()
    core.rag_transport = httpx.MockTransport(fake)
    return fake


def test_forwards_verbatim_and_returns_upstream_bytes(agent, upstream):
    body = b'{"query":"bearing temperature limits","collection_names":["demo_corpus"]}'
    response = agent.post("/ragproxy/v1/search?top_k=4", content=body,
                          headers={"content-type": "application/json",
                                   "authorization": "Bearer rag-key",
                                   "accept-encoding": "gzip", "connection": "keep-alive"})
    assert response.status_code == 200
    assert response.content == upstream.body
    assert response.headers["x-rag-trace"] == "t-1"
    sent = upstream.requests[0]
    assert str(sent.url) == "http://rag-server:8081/v1/search?top_k=4"
    assert sent.method == "POST"
    assert sent.content == body
    assert sent.headers["authorization"] == "Bearer rag-key"
    assert sent.headers.get("accept-encoding") in (None, "identity", "gzip, deflate")
    assert "gzip" != sent.headers.get("accept-encoding")


def test_upstream_errors_pass_through_unchanged(agent, upstream):
    upstream.status = 422
    upstream.body = b'{"detail":"collection not found"}'
    response = agent.post("/ragproxy/v1/search", content=b"{}")
    assert response.status_code == 422
    assert response.content == upstream.body


def test_unreachable_upstream_is_502(agent, upstream):
    upstream.raise_error = httpx.ConnectError("refused")
    response = agent.post("/ragproxy/v1/search", content=b'{"query":"x"}')
    assert response.status_code == 502
    assert "unreachable" in response.json()["detail"]


def test_get_passthrough_emits_no_events(agent, operator, upstream):
    incident = inject(operator)
    upstream.body = b'{"message":"healthy"}'
    assert agent.get("/ragproxy/v1/health").json() == {"message": "healthy"}
    types = [e["type"] for e in operator.get(f"/api/v1/incidents/{incident['id']}/events").json()]
    assert "retrieval.query" not in types


def test_retrieval_events_attach_to_incident_in_flight(agent, operator, upstream):
    incident = inject(operator)
    agent.post("/ragproxy/v1/search", json={"query": "bearing temperature limits"})
    events = operator.get(f"/api/v1/incidents/{incident['id']}/events").json()
    query = next(e for e in events if e["type"] == "retrieval.query")
    result = next(e for e in events if e["type"] == "retrieval.result")
    assert query["query"] == "bearing temperature limits"
    assert result["status"] == 200 and result["latency_ms"] >= 0
    assert [d["document_name"] for d in result["documents"]] == ["manual-01.md", "log-01.md"]


def test_unreachable_upstream_emits_error_result(agent, operator, upstream):
    incident = inject(operator)
    upstream.raise_error = httpx.ConnectError("refused")
    agent.post("/ragproxy/v1/search", json={"query": "x"})
    result = [e for e in operator.get(f"/api/v1/incidents/{incident['id']}/events").json()
              if e["type"] == "retrieval.result"][0]
    assert result["status"] == 502 and "unreachable" in result["error"]


def test_no_incident_means_no_events_but_forward_works(agent, operator, upstream):
    assert agent.post("/ragproxy/v1/search", json={"query": "x"}).status_code == 200
    assert operator.get("/api/v1/incidents").json() == []


def test_v1_suffix_is_load_bearing(agent, upstream):
    assert agent.post("/ragproxy/search", content=b"{}").status_code == 404
    assert agent.post("/ragproxy/v2/search", content=b"{}").status_code == 404
    assert upstream.requests == []


def test_query_text_extraction():
    assert ragproxy.query_text(b'{"query": "q1"}') == "q1"
    assert ragproxy.query_text(b'{"messages": [{"role": "system", "content": "s"},'
                               b'{"role": "user", "content": "q2"}]}') == "q2"
    assert ragproxy.query_text(b"not json") is None
    assert ragproxy.query_text(b"[1, 2]") is None
    assert ragproxy.query_text(b'{"other": 1}') is None


def test_result_documents_from_json_and_sse():
    sse = ("data: " + json.dumps({"choices": [], "citations": {"results": [
        {"document_name": "manual-01.md", "content": "limit", "score": 0.9}]}}) + "\n\n"
        "data: " + json.dumps({"citations": {"results": [
            {"document_name": "manual-01.md", "content": "limit", "score": 0.9}]}}) + "\n\n"
        "data: [DONE]\n\n")
    docs = ragproxy.result_documents(sse.encode())
    assert [d["document_name"] for d in docs] == ["manual-01.md"]  # de-duplicated
    assert ragproxy.result_documents(b"garbage") == []
    assert ragproxy.result_documents(b"[]") == []


def test_streaming_response_is_relayed_without_buffering(ops, core):
    """ASGI-level proof: the first chunk reaches the client while the
    upstream is still holding the second."""
    gate = asyncio.Event()

    async def stream():
        yield b'data: {"choices":[{"delta":{"content":"Bearing"}}]}\n\n'
        await gate.wait()
        yield b"data: [DONE]\n\n"

    def handler(request):
        return httpx.Response(200, content=stream(),
                              headers={"content-type": "text/event-stream"})

    core.rag_transport = httpx.MockTransport(handler)
    app = apps.create_agent_app(ops)

    async def run():
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": "/ragproxy/v1/generate",
                 "raw_path": b"/ragproxy/v1/generate", "query_string": b"",
                 "headers": [(b"content-type", b"application/json")],
                 "client": ("test", 1), "server": ("test", 8090), "root_path": ""}
        sent_body = False
        first_chunk = asyncio.Event()
        messages = []

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": b'{"messages":[]}', "more_body": False}
            await asyncio.sleep(3600)

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                first_chunk.set()

        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(first_chunk.wait(), 5)
        bodies = [m["body"] for m in messages if m["type"] == "http.response.body"]
        assert b"".join(bodies).startswith(b'data: {"choices"')
        assert b"[DONE]" not in b"".join(bodies)
        gate.set()
        await asyncio.wait_for(task, 5)
        assert b"[DONE]" in b"".join(m.get("body", b"") for m in messages
                                     if m["type"] == "http.response.body")

    asyncio.run(run())
