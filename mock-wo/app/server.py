"""Process entrypoint — two uvicorn servers, one event loop, one Core.

ADR-V08: the agent app listens on :8090 and the operator app on :8091, in a
single process, so they share the SQLite store and the in-memory event bus
(an agent-port write reaches operator-port SSE without a broker), and the
single-process SQLite discipline of spec/03 holds.

uvicorn installs its own SIGINT/SIGTERM handlers per server, and the last
server to start would win — the other would never exit and ``docker stop``
would hang to the kill timeout. Signal capture is disabled per server and
one handler here stops both. If either server stops for any reason, the
other is told to stop too: a half-up mock-wo is worse than a restarted one.

An open SSE connection would also hold graceful shutdown forever (uvicorn
waits for connections to close). Stopping ends every stream through the
bus, and a bounded graceful timeout backs that up.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import List, Optional, Tuple

import uvicorn

from .apps import create_agent_app, create_operator_app
from .clients import DevFakeVss, DisabledVss, DisabledWake
from .core import Core, Settings
from .ops import Operations

log = logging.getLogger("mock-wo")


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):  # noqa: D401 - uvicorn hook
        yield


def build(settings: Settings, **overrides) -> Tuple[Core, Operations]:
    core = Core.build(settings, **overrides)
    return core, Operations(core)


GRACEFUL_SHUTDOWN_SECONDS = 5


def make_servers(settings: Settings, ops: Operations,
                 log_level: str = "info") -> List[_Server]:
    agent = create_agent_app(ops)
    operator = create_operator_app(ops)
    servers = [
        _Server(uvicorn.Config(agent, host=settings.host, port=settings.agent_port,
                               log_level=log_level, lifespan="on",
                               timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS)),
        _Server(uvicorn.Config(operator, host=settings.host,
                               port=settings.operator_port, log_level=log_level,
                               lifespan="on",
                               timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS)),
    ]
    for server in servers:
        server.ops = ops  # type: ignore[attr-defined]
    return servers


async def run(servers: List[_Server],
              stop: Optional[asyncio.Event] = None) -> None:
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, stop.set)

    async def watch_stop():
        await stop.wait()
        for server in servers:
            server.should_exit = True
            ops = getattr(server, "ops", None)
            if ops is not None:
                ops.core.bus.close_all()

    async def serve(server: _Server):
        try:
            await server.serve()
        finally:
            stop.set()

    watcher = asyncio.create_task(watch_stop())
    try:
        await asyncio.gather(*(serve(s) for s in servers))
    finally:
        watcher.cancel()


def main() -> None:  # pragma: no cover - exercised by the container smoke
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    core, ops = build(settings)
    if isinstance(core.vss, DevFakeVss):
        log.warning("MOCK_WO_DEV_FAKE_CLIENTS=1: VSS and the wake hook are FAKED."
                    " Dev machine only — never set this on the lab VM.")
    if isinstance(core.vss, DisabledVss):
        log.warning("VSS client disabled (VSS_AGENT_URL / VST_URL unset):"
                    " inject and ask-the-footage will report errors")
    if isinstance(core.wake, DisabledWake):
        log.warning("wake hook disabled (OPENCLAW_HOOK_URL / OPENCLAW_HOOK_TOKEN"
                    " unset): the agent will not be woken")
    log.info("packs loaded: %s", ", ".join(sorted(core.packs)) or "none")
    asyncio.run(run(make_servers(settings, ops)))


if __name__ == "__main__":  # pragma: no cover
    main()
