"""The real process shape (ADR-V08): two uvicorn servers on two ports in one
event loop, sharing one Core. An agent-port write reaches operator-port SSE.
"""

import asyncio
import json
import socket
import threading
import time

import httpx

from app import server
from conftest import evidence_payload


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_two_ports_one_core_and_live_sse(settings, fake_vss, fake_wake):
    settings.host = "127.0.0.1"
    settings.agent_port = _free_port()
    settings.operator_port = _free_port()
    _core, ops = server.build(settings, vss=fake_vss, wake=fake_wake)
    servers = server.make_servers(settings, ops, log_level="warning")
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()
    thread = threading.Thread(target=lambda: loop.run_until_complete(server.run(servers, stop)),
                              daemon=True)
    thread.start()
    agent = f"http://127.0.0.1:{settings.agent_port}"
    operator = f"http://127.0.0.1:{settings.operator_port}"
    try:
        deadline = time.monotonic() + 10
        while not all(s.started for s in servers):
            assert time.monotonic() < deadline, "servers did not start"
            time.sleep(0.05)
        assert httpx.get(f"{agent}/health").json()["port"] == "agent"
        assert httpx.get(f"{operator}/health").json()["port"] == "operator"
        # The decision route does not exist on the agent port of the real process.
        assert httpx.post(f"{agent}/api/v1/proposals/x/decision", json={}).status_code == 404

        received = []
        connected = threading.Event()

        def listen():
            with httpx.stream("GET", f"{operator}/api/v1/stream", timeout=10) as response:
                assert response.headers["content-type"].startswith("text/event-stream")
                for line in response.iter_lines():
                    if line.startswith(": connected"):
                        connected.set()
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        received.append(event)
                        if event["type"] == "evidence.added":
                            return

        listener = threading.Thread(target=listen, daemon=True)
        listener.start()
        assert connected.wait(5)
        incident = httpx.post(f"{operator}/api/v1/incidents/inject",
                              json={"asset_id": "M-1", "incident_id": "M1-BEARING"}).json()
        deadline = time.monotonic() + 5
        while httpx.get(f"{operator}/api/v1/incidents/{incident['id']}").json()["stage"] != "gather":
            assert time.monotonic() < deadline
            time.sleep(0.05)
        created = httpx.post(f"{agent}/api/v1/evidence", json=evidence_payload(incident["id"]))
        assert created.status_code == 201
        listener.join(5)
        types = [e["type"] for e in received]
        assert types[0] == "stage.changed" and "evidence.added" in types
        seqs = [e["seq"] for e in received if e["incident_id"] == incident["id"]]
        assert seqs == sorted(seqs)
        # Keep a live SSE connection open while stopping: it must not hold the
        # process up (the docker-stop hang this guards against).
        held = threading.Thread(target=lambda: _hold_stream(operator), daemon=True)
        held.start()
        time.sleep(0.5)
        stopped_at = time.monotonic()
    finally:
        loop.call_soon_threadsafe(stop.set)
        thread.join(15)
    assert not thread.is_alive(), "stopping must stop both servers"
    assert time.monotonic() - stopped_at < server.GRACEFUL_SHUTDOWN_SECONDS, (
        "an open SSE stream held shutdown")
    assert all(s.should_exit for s in servers)


def _hold_stream(operator):
    try:
        with httpx.stream("GET", f"{operator}/api/v1/stream", timeout=30) as response:
            for _ in response.iter_lines():
                pass
    except httpx.HTTPError:
        pass
