"""L3 contracts for the operator dashboard packaging (operator-dashboard-spec
ADR-V06, ADR-V08, D6). Structure only — no Docker daemon needed.

The security property these pin: the agent can reach mock-wo's agent port
and nothing that carries the approval gate.
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def test_mock_wo_compose_publishes_both_ports_and_mounts_packs_read_only():
    service = yaml.safe_load((REPO / "compose/mock-wo.yml").read_text())["services"]["mock-wo"]
    assert "8090:8090" in service["ports"]
    assert "8091:8091" in service["ports"]
    volumes = service["volumes"]
    assert "../packs:/packs:ro" in volumes
    assert "../fixtures:/fixtures:ro" in volumes
    env = service["environment"]
    assert env["MOCK_WO_PACKS_DIR"] == "/packs"
    # Never the dev-only fake clients in the lab compose.
    assert "MOCK_WO_DEV_FAKE_CLIENTS" not in env
    assert all("8091" not in str(v) for k, v in env.items() if k != "MOCK_WO_OPERATOR_PORT")
    health = " ".join(service["healthcheck"]["test"])
    assert "8090" in health and "8091" in health


def test_nemoclaw_policy_never_grants_the_operator_port_or_rag():
    script = (REPO / "scripts/prep/40-nemoclaw.sh").read_text()
    lab = re.search(r"^LAB_ENDPOINTS=\(([^)]*)\)", script, re.M)
    forbidden = re.search(r"^FORBIDDEN_ENDPOINTS=\(([^)]*)\)", script, re.M)
    assert lab and forbidden
    granted = lab.group(1).split()
    assert "8090" in granted
    assert "8091" not in granted and "8081" not in granted
    assert set(forbidden.group(1).split()) >= {"8091", "8081"}
    # The generated policy is checked against the forbidden list before apply.
    assert 'for port in "${FORBIDDEN_ENDPOINTS[@]}"' in script


def test_runtime_image_carries_no_node_and_serves_both_ports():
    dockerfile = (REPO / "mock-wo/Dockerfile").read_text()
    stages = re.split(r"^FROM ", dockerfile, flags=re.M)[1:]
    assert len(stages) == 2, "UI build stage + runtime stage"
    assert stages[0].startswith("node:22.23.0-bookworm-slim AS ui")
    runtime = stages[1]
    assert runtime.startswith("python:3.12-slim")
    assert "npm" not in runtime and "node" not in runtime.replace("COPY --from=ui", "")
    assert "COPY --from=ui /ui/dist ./app/ui_dist" in runtime
    assert "EXPOSE 8090 8091" in runtime
    assert 'ENTRYPOINT ["python", "-m", "app.server"]' in runtime
    assert "npm ci" in stages[0], "the UI installs from the committed lockfile"
    assert (REPO / "mock-wo/ui/package-lock.json").is_file()


def test_ui_and_plugin_dependencies_are_pinned_exactly():
    import json
    for manifest in ("mock-wo/ui/package.json", "openclaw/plugins/mock-wo-telemetry/package.json"):
        data = json.loads((REPO / manifest).read_text())
        for section in ("dependencies", "devDependencies"):
            for name, version in data.get(section, {}).items():
                assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{manifest}: {name}@{version} is not an exact pin"


def test_telemetry_plugin_manifest_registers_no_tools():
    import json
    manifest = json.loads((REPO / "openclaw/plugins/mock-wo-telemetry/openclaw.plugin.json").read_text())
    assert manifest["id"] == "mock-wo-telemetry"
    assert "contracts" not in manifest or not manifest["contracts"].get("tools")
    source = (REPO / "openclaw/plugins/mock-wo-telemetry/src/index.ts").read_text()
    assert "registerTool" not in source


def test_dev_simulator_is_labelled_and_only_uses_the_agent_port():
    source = (REPO / "scripts/dev/simulate-agent.py").read_text()
    assert "DEV ONLY" in source
    assert "8091" not in source
    assert "/decision" not in source
