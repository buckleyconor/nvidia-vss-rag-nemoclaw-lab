"""Event bus, SSE framing, and the outbound HTTP clients (VSS, wake hook)."""

import asyncio
import json

import httpx
import pytest

from app import clients, events


def test_format_sse_incident_and_global():
    frame = events.format_sse({"type": "stage.changed", "incident_id": "i1", "seq": 3,
                               "ts": "t", "stage": "gather"})
    lines = frame.strip().split("\n")
    assert lines[0] == "event: stage.changed"
    assert lines[1] == "id: i1:3"
    assert json.loads(lines[2][len("data: "):])["stage"] == "gather"
    assert frame.endswith("\n\n")
    global_frame = events.format_sse({"type": "demo.reset", "incident_id": None, "seq": 0,
                                      "ts": "t"})
    assert "id:" not in global_frame


def test_bus_rejects_unknown_types(ops):
    with pytest.raises(ValueError):
        ops.core.bus.publish_global("stage.changed")
    with ops._tx() as tx:
        with pytest.raises(ValueError):
            ops.core.bus.record(tx.conn, tx.events, "i", "demo.reset", {})
        with pytest.raises(ValueError):
            ops.core.bus.record(tx.conn, tx.events, "i", "made.up", {})


def test_fanout_delivers_overflows_and_drops_closed_loops():
    bus = events.EventBus()

    async def scenario():
        loop = asyncio.get_running_loop()
        sub = bus.subscribe(loop)
        bus.fanout([{"type": "demo.reset", "incident_id": None, "seq": 0}])
        await asyncio.sleep(0)
        assert (await sub.queue.get())["type"] == "demo.reset"
        for _ in range(events.QUEUE_LIMIT + 5):
            bus.fanout([{"type": "error", "incident_id": "i", "seq": 1}])
        await asyncio.sleep(0.05)
        assert sub.overflowed is True
        assert bus.subscriber_count == 1
        bus.unsubscribe(sub)
        bus.unsubscribe(sub)  # idempotent
        assert bus.subscriber_count == 0

    asyncio.run(scenario())

    async def closing():
        loop = asyncio.get_running_loop()
        sub = bus.subscribe(loop)
        for _ in range(events.QUEUE_LIMIT):
            sub.queue.put_nowait({"type": "error"})
        bus.close_all()  # full queue: the close marker still gets in
        await asyncio.sleep(0.01)
        items = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
        assert items[-1] is events.CLOSE
        bus.unsubscribe(sub)

    asyncio.run(closing())
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    bus.subscribe(closed_loop)
    bus.close_all()
    assert bus.subscriber_count == 0
    bus.subscribe(closed_loop)
    bus.fanout([{"type": "demo.reset"}])
    assert bus.subscriber_count == 0
    bus.fanout([])


# -- HTTP clients -----------------------------------------------------------------

def test_http_vss_uploads_when_sensor_missing_and_asks(tmp_path):
    clip = tmp_path / "clip-anomaly-01.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/vst/api/v1/sensor/list":
            return httpx.Response(200, json=[{"name": "other"}, "junk"])
        if request.method == "PUT":
            assert request.content == clip.read_bytes()
            return httpx.Response(200, json={"id": "s1"})
        if request.url.path == "/generate":
            message = json.loads(request.content)["input_message"]
            assert "video_understanding" in message and "clip-anomaly-01" in message
            return httpx.Response(200, json={
                "value": "<agent-think><agent-think-step>x</agent-think-step></agent-think>\n\n"
                         "Fluid is visible.\n"})
        return httpx.Response(404)

    vss = clients.HttpVss("http://vss:8000/", "http://vst:30888", transport=httpx.MockTransport(handler))
    assert vss.ensure_clip(clip) == "clip-anomaly-01"
    assert seen[1][0] == "PUT" and seen[1][1] == "/vst/api/v1/storage/file/clip-anomaly-01.mp4"
    assert seen[1][2] == {"timestamp": clients.DEFAULT_CLIP_TIMESTAMP}
    assert vss.ask("clip-anomaly-01", "Any fluid?").text == "Fluid is visible."


def test_http_vss_skips_upload_when_sensor_present(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json=[{"name": "a"}])

    vss = clients.HttpVss("http://vss", "http://vst", transport=httpx.MockTransport(handler))
    assert vss.ensure_clip(clip) == "a"
    assert calls == ["GET"]


@pytest.mark.parametrize("response", [
    httpx.Response(500),
    httpx.Response(200, json={"value": "<agent-think>only thinking</agent-think>"}),
    httpx.Response(200, content=b"not json"),
])
def test_http_vss_failures_raise_unavailable(tmp_path, response):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x")
    vss = clients.HttpVss("http://vss", "http://vst",
                          transport=httpx.MockTransport(lambda r: response))
    with pytest.raises(clients.ClientUnavailable):
        vss.ask("a", "question?")
    if response.status_code == 500:
        with pytest.raises(clients.ClientUnavailable):
            vss.ensure_clip(clip)


def test_http_wake_posts_bearer_and_text():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    wake = clients.HttpWake("http://host.docker.internal:18789/", "tok",
                            transport=httpx.MockTransport(handler))
    wake.wake("incident i1")
    assert captured == {"url": "http://host.docker.internal:18789/hooks/wake",
                        "auth": "Bearer tok", "body": {"text": "incident i1", "mode": "now"}}
    refused = clients.HttpWake("http://h", "bad", transport=httpx.MockTransport(
        lambda r: httpx.Response(401)))
    with pytest.raises(clients.ClientUnavailable):
        refused.wake("x")


def test_disabled_clients_explain_themselves(tmp_path):
    with pytest.raises(clients.ClientUnavailable, match="GPU VM"):
        clients.DisabledVss().ensure_clip(tmp_path / "a.mp4")
    with pytest.raises(clients.ClientUnavailable, match="GPU VM"):
        clients.DisabledVss().ask("a", "b")
    with pytest.raises(clients.ClientUnavailable, match="GPU VM"):
        clients.DisabledWake().wake("x")


def test_core_builds_http_clients_from_settings(tmp_path):
    from app.core import Core, Settings
    settings = Settings(db_path=str(tmp_path / "db"), packs_dir=tmp_path,
                        vss_agent_url="http://vss:8000", vst_url="http://vst:30888",
                        hook_url="http://hook", hook_token="t")
    core = Core.build(settings)
    assert isinstance(core.vss, clients.HttpVss)
    assert isinstance(core.wake, clients.HttpWake)
    bare = Core.build(Settings(db_path=str(tmp_path / "db2"), packs_dir=tmp_path))
    assert isinstance(bare.vss, clients.DisabledVss)
    assert isinstance(bare.wake, clients.DisabledWake)


def test_settings_from_env(monkeypatch):
    from app.core import Settings
    monkeypatch.setenv("MOCK_WO_DB_PATH", "/tmp/x.db")
    monkeypatch.setenv("MOCK_WO_OPERATOR_PORT", "9191")
    monkeypatch.setenv("OPENCLAW_HOOK_TOKEN", "abc")
    settings = Settings.from_env()
    assert settings.db_path == "/tmp/x.db"
    assert settings.operator_port == 9191 and settings.agent_port == 8090
    assert settings.hook_token == "abc"


def test_dev_fake_clients_only_when_flagged_and_never_over_real_config(tmp_path):
    from app.core import Core, Settings
    dev = Core.build(Settings(db_path=str(tmp_path / "a"), packs_dir=tmp_path,
                              dev_fake_clients=True))
    assert isinstance(dev.vss, clients.DevFakeVss)
    assert isinstance(dev.wake, clients.DevFakeWake)
    assert dev.vss.ensure_clip(tmp_path / "clip-x.mp4") == "clip-x"
    assert "no model ran" in dev.vss.ask("clip-x", "any smoke?").text
    assert dev.wake.wake("x") is None
    real = Core.build(Settings(db_path=str(tmp_path / "b"), packs_dir=tmp_path,
                               dev_fake_clients=True, vss_agent_url="http://v",
                               vst_url="http://t", hook_url="http://h", hook_token="k"))
    assert isinstance(real.vss, clients.HttpVss)
    assert isinstance(real.wake, clients.HttpWake)


def test_health_flags_dev_fake_clients(tmp_path, packs_dir):
    from fastapi.testclient import TestClient
    from app import apps
    from app.core import Core, Settings
    from app.ops import Operations
    core = Core.build(Settings(db_path=str(tmp_path / "c"), packs_dir=packs_dir,
                               dev_fake_clients=True))
    with TestClient(apps.create_agent_app(Operations(core))) as client:
        assert client.get("/health").json()["dev_fake_clients"] is True
