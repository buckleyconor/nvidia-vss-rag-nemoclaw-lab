#!/usr/bin/env python3
"""lab-nemoclaw-hook-relay — host-side OpenClaw wake-hook bridge (O2, 2026-09-13).

Why it exists
-------------
mock-wo wakes the NemoClaw agent with the `nemoclaw-lab-cl` wake-hook pattern:
POST <base>/hooks/wake, Bearer token, body {"text", "mode"}. That pattern did
NOT port to NemoClaw v0.0.118 / OpenClaw 2026.7.1 on this VM (2026-09-13,
O2 verified on the VM): the sandbox dashboard port 18789 answers GET / but
returns 404 for POST /hooks/wake, 18790 is not listening, and `openclaw
hooks list` shows only the five internal lifecycle hooks (boot-md,
bootstrap-extra, command-logger, compaction, session-memory) — there is no
HTTP wake endpoint in this version.

The vendor's host forward publishes the dashboard (18789) only. So this
relay is the lab-owned bridge O2 anticipated: it accepts the wake POST and
translates it into the CURRENT agent-turn surface —
    nemoclaw demo agent --agent main -m "<text>"
(one non-interactive turn in the sandbox's main agent session; flags per
`nemoclaw demo agent --help`, checked 2026-09-13).

Contract
--------
- Binds 172.18.0.1:18790 (the demo-net bridge gateway IP, port 18790 — the
  port the vendor's own sandbox policy already references alongside 18789
  and which the vendor forward leaves unused). Only containers on demo-net
  can reach it (mock-wo via host.docker.internal:host-gateway); it is NOT on
  loopback, 0.0.0.0, or any NemoClaw-managed port.
- Auth: Authorization: Bearer <token>, token read from
  /root/.config/lab/nemoclaw-hook-token (root 600, gitignored). The token is
  the sandbox agent's gateway token (`nemoclaw demo gateway-token`); it
  survives gateway restarts and container stop/start (state-pinned) but must
  be re-written after a clean re-onboard (heal-ladder tier 3 nuclear).
- POST /hooks/wake with valid token + non-empty "text":
    202 Accepted immediately; the agent turn runs in the background, one at
    a time (a busy relay answers 409 — OpenClaw sessions are single-turn
    anyway). mock-wo's HttpWake (10 s timeout) gets its answer without
    waiting for the model turn.
- GET /health -> 200 {"ok":true} (liveness for humans; the relay is
  host-side, so the docker-based health-watch deliberately does not probe
  it — it is monitored by systemd).
- Every wake is logged to /var/log/nemoclaw-hook-relay.log with the turn
  exit code (the audit trail for the demo's beat structure).

Run by lab-nemoclaw-hook-relay.service (root). Safe to run manually:
  sudo /usr/bin/python3 /usr/local/lib/lab/nemoclaw-hook-relay.py
"""

import http.server
import json
import os
import subprocess
import threading
import time

HOST = os.environ.get("HOOK_RELAY_BIND", "172.18.0.1")
PORT = int(os.environ.get("HOOK_RELAY_PORT", "18790"))
TOKEN_FILE = os.environ.get("HOOK_RELAY_TOKEN_FILE",
                            "/root/.config/lab/nemoclaw-hook-token")
LOG = os.environ.get("HOOK_RELAY_LOG", "/var/log/nemoclaw-hook-relay.log")
CLI = os.environ.get("NEMO_CLI", "/root/.local/bin/nemoclaw")
SANDBOX = os.environ.get("NEMO_SANDBOX", "demo")
AGENT_ID = os.environ.get("NEMO_AGENT_ID", "main")
TURN_TIMEOUT = 900   # one agent turn budget (s); the model is remote via the shim

ENV = dict(os.environ, NEMOCLAW_GATEWAY_PORT="8085")
LOCK = threading.Lock()
BUSY = False


def log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(LOG, "a") as fh:
        fh.write(f"{stamp} {msg}\n")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "lab-nemoclaw-hook-relay/1"

    def _token(self) -> str:
        try:
            with open(TOKEN_FILE) as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def _authed(self) -> bool:
        tok = self._token()
        return bool(tok) and self.headers.get("Authorization", "") == f"Bearer {tok}"

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path == "/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):  # noqa: N802
        if self.path != "/hooks/wake":
            self.send_response(404)
            self.end_headers()
            return
        if not self._authed():
            log(f"wake rejected: bad or missing Bearer token (from {self.client_address[0]})")
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            text = str(body.get("text", "")).strip()
        except (ValueError, TypeError):
            self.send_response(400)
            self.end_headers()
            return
        if not text:
            self.send_response(400)
            self.end_headers()
            return
        global BUSY  # noqa: PLW0603
        with LOCK:
            if BUSY:
                log("wake rejected: a turn is already running")
                self.send_response(409)
                self.end_headers()
                return
            BUSY = True
        self.send_response(202)
        self.end_headers()
        log(f"wake accepted from {self.client_address[0]}: {len(text)} chars")

        def run_turn() -> None:
            global BUSY  # noqa: PLW0603
            try:
                proc = subprocess.run(
                    [CLI, SANDBOX, "agent", "--agent", AGENT_ID, "-m", text],
                    env=ENV, timeout=TURN_TIMEOUT,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                log(f"wake turn finished rc={proc.returncode}")
                if proc.returncode != 0:
                    log(f"wake turn stderr tail: {proc.stderr[-500:].decode(errors='replace').strip()}")
            except subprocess.TimeoutExpired:
                log("wake turn FAILED: timed out "
                    f"({TURN_TIMEOUT}s budget) — the session may need a human look")
            except Exception as exc:  # noqa: BLE001 (relay must survive anything)
                log(f"wake turn FAILED: {exc!r}")
            finally:
                with LOCK:
                    BUSY = False

        threading.Thread(target=run_turn, daemon=True).start()

    def log_message(self, fmt, *args):  # keep the systemd journal quiet
        pass


def main() -> None:
    log(f"relay starting on {HOST}:{PORT} (token file {TOKEN_FILE})")
    http.server.ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
