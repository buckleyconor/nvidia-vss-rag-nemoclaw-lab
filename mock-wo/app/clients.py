"""Outbound clients: VSS (clip submission, ask-the-footage) and the OpenClaw
wake hook. Both are interfaces with an HTTP implementation for the GPU VM
and a *disabled* implementation that fails loudly — the dev machine has no
VSS and no NemoClaw, and an unconfigured client must surface as a visible
``error`` event, never as a silent success (§8.4 "silence reads as
breakage").

Request shapes follow the VSS v3.2.1 skills (checked 2026-09-13):
``vss-ask-video`` — VST sensor list + ``PUT /vst/api/v1/storage/file/<name>``
upload, then ``POST <agent>/generate`` with an ``input_message`` asking for
the ``video_understanding`` tool; the answer is ``.value`` with
``<agent-think>`` blocks stripped. The wake hook is ``POST <hook>/hooks/wake``
with a Bearer token (``nemoclaw-lab-cl`` pattern; body shape verified on the
VM — O2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

import httpx

THINK_RE = re.compile(r"<agent-think>.*?</agent-think>\s*", re.S)
DEFAULT_CLIP_TIMESTAMP = "2025-01-01T00:00:00.000Z"


class ClientUnavailable(RuntimeError):
    """The dependency is not configured or not reachable."""


@dataclass
class AskAnswer:
    text: str
    t_start: Optional[float] = None
    t_end: Optional[float] = None


class VssClient(Protocol):
    def ensure_clip(self, clip_path: Path) -> str: ...

    def ask(self, sensor: str, question: str) -> AskAnswer: ...


class WakeClient(Protocol):
    def wake(self, text: str) -> None: ...


class DisabledVss:
    def ensure_clip(self, clip_path: Path) -> str:
        raise ClientUnavailable(
            "VSS is not configured (VSS_AGENT_URL / VST_URL unset) — this"
            " step runs on the GPU VM")

    def ask(self, sensor: str, question: str) -> AskAnswer:
        raise ClientUnavailable(
            "VSS is not configured (VSS_AGENT_URL unset) — ask-the-footage"
            " runs on the GPU VM")


class DisabledWake:
    def wake(self, text: str) -> None:
        raise ClientUnavailable(
            "OpenClaw wake hook is not configured (OPENCLAW_HOOK_URL unset)"
            " — the agent runs on the GPU VM")


class DevFakeVss:
    """DEV MACHINE ONLY (MOCK_WO_DEV_FAKE_CLIENTS=1): pretends the clip is in
    VSS so an incident can reach gather without a GPU stack. Asks are answered
    with an explicit placeholder that no one could mistake for model output."""

    def ensure_clip(self, clip_path: Path) -> str:
        return sensor_name(clip_path)

    def ask(self, sensor: str, question: str) -> AskAnswer:
        return AskAnswer(text=f"[dev fake VSS — no model ran] You asked about"
                              f" {sensor}: {question}")


class DevFakeWake:
    """DEV MACHINE ONLY: accepts the wake and wakes nothing. Drive the agent
    side with scripts/dev/simulate-agent.py."""

    def wake(self, text: str) -> None:
        return None


def sensor_name(clip_path: Path) -> str:
    """VST names an uploaded file's sensor after the filename stem."""
    return clip_path.stem


class HttpVss:
    def __init__(self, agent_url: str, vst_url: str,
                 timeout: float = 120.0,
                 transport: Optional[httpx.BaseTransport] = None) -> None:
        self._agent = agent_url.rstrip("/")
        self._vst = vst_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, transport=self._transport)

    def ensure_clip(self, clip_path: Path) -> str:
        sensor = sensor_name(clip_path)
        try:
            with self._client() as client:
                listing = client.get(f"{self._vst}/vst/api/v1/sensor/list")
                listing.raise_for_status()
                names = {s.get("name") for s in listing.json()
                         if isinstance(s, dict)}
                if sensor in names:
                    return sensor
                with clip_path.open("rb") as fh:
                    upload = client.put(
                        f"{self._vst}/vst/api/v1/storage/file/{clip_path.name}",
                        params={"timestamp": DEFAULT_CLIP_TIMESTAMP},
                        headers={"Content-Type": "application/octet-stream"},
                        content=fh.read(),
                    )
                upload.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClientUnavailable(f"VST clip upload failed: {exc}") from exc
        return sensor

    def ask(self, sensor: str, question: str) -> AskAnswer:
        message = ("Call video_understanding tool to answer the following"
                   f" question about {sensor}: {question}")
        try:
            with self._client() as client:
                response = client.post(f"{self._agent}/generate",
                                       json={"input_message": message})
                response.raise_for_status()
                value = response.json().get("value", "")
        except (httpx.HTTPError, ValueError) as exc:
            raise ClientUnavailable(f"VSS /generate failed: {exc}") from exc
        text = THINK_RE.sub("", value or "").strip()
        if not text:
            raise ClientUnavailable("VSS /generate returned no answer")
        return AskAnswer(text=text)


class HttpWake:
    def __init__(self, hook_url: str, token: str, timeout: float = 10.0,
                 transport: Optional[httpx.BaseTransport] = None) -> None:
        self._url = hook_url.rstrip("/") + "/hooks/wake"
        self._token = token
        self._timeout = timeout
        self._transport = transport

    def wake(self, text: str) -> None:
        try:
            with httpx.Client(timeout=self._timeout,
                              transport=self._transport) as client:
                response = client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={"text": text, "mode": "now"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClientUnavailable(f"wake hook failed: {exc}") from exc
