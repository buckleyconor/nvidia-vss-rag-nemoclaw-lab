"""L3 contract suite (05: TC-032..TC-038 + TC-041) — the shim
compose/nginx contract, the config/ overlays, version hygiene and
.gitignore secret hygiene.

Repo-level suite (the closing gate runs `pytest mock-wo/tests tests`).
YAML parsing uses the pinned dev dependency pyyaml (03 dev table, added
at M4 — 08 item 35).
"""

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
PIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==\d+\.\d+\.\d+([.-][A-Za-z0-9.]+)?$")


def _env_lines(path: Path) -> dict:
    """Parse a .env file: KEY=VALUE lines; comments/blanks skipped;
    surrounding single/double quotes stripped from values."""
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = ENV_LINE.match(line)
        assert m, f"unparseable env line in {path.name}: {line!r}"
        key, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def test_tc032_shim_compose_contract():
    data = yaml.safe_load((REPO / "compose/docker-compose.shim.yml").read_text())
    shim = data["services"]["auth-shim"]
    assert shim["image"] == "nginx:1.27-alpine"
    assert "8080:8080" in shim["ports"]
    assert "demo-net" in shim["networks"]


def test_tc033_shim_nginx_template():
    text = (REPO / "compose/nginx.conf.template").read_text()
    # 05 TC-033, verbatim expected strings:
    assert 'proxy_set_header    Authorization "";' in text
    assert "x-api-key ${SHARED_API_KEY}" in text
    assert "proxy_buffering off" in text


def test_config_rag_yaml_frag_enabled():
    # 08 item 10: the M4 contract pins that the file exists, parses as
    # YAML, and enables the `frag` knowledge-retrieval tool. The exact
    # shipped content (schema; the RAG_ value reads) is verified against
    # the cloned release at prep — so the schema is NOT pinned here
    # (08 items 10 + 38).
    path = REPO / "config/config_rag.yml"
    data = yaml.safe_load(path.read_text())
    assert data, "config_rag.yml parsed empty"
    assert "frag" in yaml.safe_dump(data), "frag tool not enabled"


def test_tc034_lvs_env_example():
    values = _env_lines(REPO / "config/lvs.env.example")
    assert values["MODE"] == "2d"
    assert values["BP_PROFILE"] == "bp_developer_lvs"
    assert values["HARDWARE_PROFILE"] == "RTXPRO6000BW"
    assert values["VLM_MODE"] == "local_shared"
    assert values["VSS_AGENT_VERSION"] == "3.2.1"
    # the /v1 suffix is load-bearing (02)
    assert values["RAG_SERVER_URL"] == "http://rag-server:8081/v1"
    assert values["KNOWLEDGE_COLLECTION"] == "demo_corpus"
    assert values["LLM_ENDPOINT_URL"] == "http://auth-shim:8080"
    # LLM_MODE present, non-empty (value verified at prep)
    assert values.get("LLM_MODE", "") != ""
    # secret fields carry placeholders only (04)
    for key in ("NGC_CLI_API_KEY", "NVIDIA_API_KEY", "RAG_API_KEY"):
        assert "<PLACEHOLDER>" in values[key], f"{key} must be a placeholder"


def test_tc034_no_real_key_material_in_repo():
    # no `nvapi-…` value anywhere in the repo (04/TC-034). Scans every
    # text file EXCEPT: .venv (pinned dependencies), spec/ and tests/
    # (documentation/tests that quote the pattern itself), .git.
    pattern = "nvapi-"
    offenders = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO)
        if rel.parts and rel.parts[0] in (".venv", "spec", "tests", ".git"):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue  # binary
        if pattern in text:
            offenders.append(str(rel))
    assert not offenders, f"key-material pattern found in: {offenders}"


def test_tc035_rag_env():
    values = _env_lines(REPO / "config/rag.env")
    assert values["APP_VECTORSTORE_NAME"] == "elasticsearch"
    assert (values["APP_LLM_MODELNAME"]
            == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    assert values["APP_LLM_SERVERURL"] == "auth-shim:8080"
    assert (values["APP_EMBEDDINGS_MODELNAME"]
            == "nvidia/llama-nemotron-embed-1b-v2")
    # the lab runs the text-embedding NIM, not the vlm variant (M5 finding
    # from the RAG v2.6.2 compose defaults — the blueprint .env points at
    # the vlm NIM, which the lab never starts)
    assert values["APP_EMBEDDINGS_SERVERURL"] == "nemotron-embedding-ms:8000/v1"
    assert (values["APP_RANKING_MODELNAME"]
            == "nvidia/llama-nemotron-rerank-1b-v2")
    assert values["MODEL_DIRECTORY"] == "/data/nim-cache"
    assert values.get("ENABLE_AGENTIC_RAG", "off").lower() == "off"


def test_tc036_vlm_env():
    values = _env_lines(REPO / "config/vlm.env")
    assert values["NIM_PASSTHROUGH_ARGS"] == (
        "--gpu-memory-utilization 0.40 --max-model-len 32768"
        " --max-num-seqs 4"
    )


def test_tc037_nemoclaw_env():
    values = _env_lines(REPO / "config/nemoclaw.env")
    assert values["NEMOCLAW_PROVIDER"] == "custom"
    assert values["NEMOCLAW_ENDPOINT_URL"] == "http://auth-shim:8080/v1"
    assert values["COMPATIBLE_API_KEY"] == "dummy"


def test_tc038_version_hygiene():
    targets = sorted(p for p in (REPO / "compose").rglob("*") if p.is_file())
    targets += [REPO / "mock-wo/Dockerfile"]
    targets += sorted(p for p in REPO.glob("**/requirements*.txt") if p.is_file())
    for path in targets:
        text = path.read_text()
        # no `latest` anywhere in compose/Dockerfile/requirements (04/05)
        assert "latest" not in text, f"`latest` found in {path.relative_to(REPO)}"
        if path.name.startswith("requirements"):
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # every requirement line is an exact pin (or a -r include)
                assert line.startswith("-r ") or PIN_RE.match(line), (
                    f"not an exact pin in {path.name}: {line!r}"
                )


def test_tc041_gitignore_secret_hygiene():
    lines = [
        line.strip()
        for line in (REPO / ".gitignore").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    # real env files covered, *.env.example templates exempted (04)
    assert "*.env" in lines
    assert "!*.env.example" in lines
    # the prep artifact is never committed
    assert "prep-log.md" in lines
    # state dirs covered
    assert "state/" in lines
