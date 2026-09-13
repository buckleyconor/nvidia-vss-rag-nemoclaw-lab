"""Shared process state: settings, packs, event bus, telemetry, clients.

One ``Core`` is built per process and handed to both the agent app (:8090)
and the operator app (:8091) — ADR-V08: two ASGI apps, one SQLite store, one
in-memory event bus.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from . import clients, db
from .events import EventBus
from .packs import Pack, load_packs
from .telemetry import TelemetryMapper

APP_DIR = Path(__file__).resolve().parent


@dataclass
class Settings:
    db_path: str = ":memory:"
    packs_dir: Path = Path("/packs")
    default_pack: Optional[str] = None
    ui_dist: Path = APP_DIR / "ui_dist"
    rag_upstream: str = "http://rag-server:8081"
    vss_agent_url: str = ""
    vst_url: str = ""
    hook_url: str = ""
    hook_token: str = ""
    host: str = "0.0.0.0"
    dev_fake_clients: bool = False
    agent_port: int = 8090
    operator_port: int = 8091

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            db_path=env.get("MOCK_WO_DB_PATH", "/data/mock-wo/work-orders.db"),
            packs_dir=Path(env.get("MOCK_WO_PACKS_DIR", "/packs")),
            default_pack=env.get("MOCK_WO_ACTIVE_PACK") or None,
            ui_dist=Path(env.get("MOCK_WO_UI_DIST", str(APP_DIR / "ui_dist"))),
            rag_upstream=env.get("RAG_UPSTREAM_URL", "http://rag-server:8081"),
            vss_agent_url=env.get("VSS_AGENT_URL", ""),
            vst_url=env.get("VST_URL", ""),
            hook_url=env.get("OPENCLAW_HOOK_URL", ""),
            hook_token=env.get("OPENCLAW_HOOK_TOKEN", ""),
            host=env.get("MOCK_WO_HOST", "0.0.0.0"),
            dev_fake_clients=env.get("MOCK_WO_DEV_FAKE_CLIENTS") == "1",
            agent_port=int(env.get("MOCK_WO_AGENT_PORT", "8090")),
            operator_port=int(env.get("MOCK_WO_OPERATOR_PORT", "8091")),
        )


@dataclass
class Core:
    settings: Settings
    packs: Dict[str, Pack]
    bus: EventBus = field(default_factory=EventBus)
    telemetry: TelemetryMapper = field(default_factory=TelemetryMapper)
    vss: clients.VssClient = field(default_factory=clients.DisabledVss)
    wake: clients.WakeClient = field(default_factory=clients.DisabledWake)
    rag_transport: object = None  # httpx transport override (tests)

    @classmethod
    def build(cls, settings: Settings, **overrides) -> "Core":
        db.init_db(settings.db_path)
        packs = overrides.pop("packs", None)
        if packs is None:
            packs = load_packs(settings.packs_dir)
        core = cls(settings=settings, packs=packs, **overrides)
        if settings.dev_fake_clients:
            # Dev machine only: real configuration always wins if present.
            if "vss" not in overrides and not (settings.vss_agent_url and settings.vst_url):
                core.vss = clients.DevFakeVss()
            if "wake" not in overrides and not (settings.hook_url and settings.hook_token):
                core.wake = clients.DevFakeWake()
        if "vss" not in overrides and settings.vss_agent_url and settings.vst_url:
            core.vss = clients.HttpVss(settings.vss_agent_url, settings.vst_url)
        if "wake" not in overrides and settings.hook_url and settings.hook_token:
            core.wake = clients.HttpWake(settings.hook_url, settings.hook_token)
        return core
