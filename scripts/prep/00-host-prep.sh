#!/usr/bin/env bash
# 00-host-prep.sh — VM host prep and verification (03 layout; 09 "Exact
# images & versions"; 10 platform constraints).
#
# Run on the learner vCD VM (root), BEFORE 10-clone-blueprints.sh. The
# platform pre-bakes most of this into the VM template (10: "template
# pre-baking"), so every step VERIFIES first — a mismatch is a prep finding
# (recorded in prep-log.md), never a silent substitution (09).
#
#   1. NVIDIA driver 580.105.08 EXACT (10 constraint 4)
#   2. Docker Engine >= 28.3.3 AND < 29.5.0 (10 constraint 8); Compose >= v2.39.1
#   3. NVIDIA Container Toolkit >= 1.17.8 + docker runtime configured
#   4. daemon.json: native.cgroupdriver=cgroupfs + default-shm-size 32g
#      (10 constraints 2, 6)
#   5. sysctl /etc/sysctl.d/99-vss.conf (10 constraint 3)
#   6. Node.js 20 (09 — NemoClaw host requirement)
#   7. /data directories (09 artifacts)
#   8. nvcr.io login from ~/.config/vss/lab.env, --password-stdin (04)
#
# Secrets: lab.env is sourced into the environment only; nothing here ever
# prints a key value (04 "Never logged (hard rule)").
set -euo pipefail
# Loud failures: under plain set -e a failing command substitution (e.g.
# `docker version` on a socket the caller may not read) dies the script
# with no message — the `|| fail` guard on the NEXT line never runs.
# errtrace + ERR trap makes every unexpected exit name its line.
set -E
trap 'echo "00-host-prep: UNEXPECTED FAIL — line $LINENO: $BASH_COMMAND" >&2' ERR

DRIVER_WANT="580.105.08"
DOCKER_MIN="28.3.3"
DOCKER_MAX="29.5.0"
COMPOSE_MIN="2.39.1"
CTK_MIN="1.17.8"
NODE_WANT=20
LAB_ENV="${LAB_ENV:-$HOME/.config/vss/lab.env}"

fail() { echo "00-host-prep: FAIL — $*" >&2; exit 1; }

command -v sudo >/dev/null 2>&1 || [ "$(id -u)" = "0" ] \
    || fail "run as root (the VM is single-user; 04 threat model)"
# Array, not a scalar: as root the expansion must vanish entirely.
# "$SUDO" with SUDO="" expands to an empty command word -> 127.
SUDO=()
[ "$(id -u)" = "0" ] || SUDO=(sudo)

if [ -t 0 ]; then
    echo "00-host-prep: this script is idempotent; re-running is safe."
fi

# ---- dpkg sanity (refuse early; 10 c4: exact driver pin) --------------------
# A broken dpkg state (typically a kernel upgrade whose postinst failed the
# pinned driver's DKMS build) makes every apt call below fail opaquely, and
# the setup_*.x scripts fall back to distro packages. Name it up front.
DPKG_AUDIT="$("${SUDO[@]}" dpkg --audit 2>/dev/null || true)"
[ -z "$DPKG_AUDIT" ] \
    || fail "dpkg has unconfigured packages — a pending kernel upgrade most likely failed the pinned driver's DKMS build (10 c4). Fix before re-running: 'dpkg --audit' lists them; usually 'apt-get purge' the new kernel image/headers + the linux-*-hwe-24.04 metapackages (or, as fallback, move /etc/kernel/postinst.d/dkms and /etc/kernel/header_postinst.d/dkms aside, 'dpkg --configure -a', restore). Broken: ${DPKG_AUDIT}"

# ---- prep-log (03: single "recorded reality" source; never keys — 04) ----
PREP_LOG="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/prep-log.md"
log() { printf '%s\n' "$*" >> "$PREP_LOG"; }
log ""
log "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — 00-host-prep: host prep (VM $(hostname))"

# ---- 1. NVIDIA driver (exact pin, 10 constraint 4) ------------------------
echo "== 1/8 NVIDIA driver $DRIVER_WANT (exact) =="
command -v nvidia-smi >/dev/null 2>&1 \
    || fail "nvidia-smi not found — the platform template must carry the NVIDIA driver (10 constraint 4)"
DRIVER_GOT=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 || true)
[ "$DRIVER_GOT" = "$DRIVER_WANT" ] \
    || fail "driver is $DRIVER_GOT, want $DRIVER_WANT exactly (the 580.x bundle satisfies RAG's CUDA >= 12.9 host requirement; the 22.04 variant 580.65.06 is NOT used — 09)"
echo "driver: $DRIVER_GOT"
log "- nvidia driver: $DRIVER_GOT (exact pin, 10 c4)"

# ---- 2. Docker Engine window (10 constraint 8) ----------------------------
echo "== 2/8 Docker Engine [${DOCKER_MIN}, ${DOCKER_MAX}) + Compose >= ${COMPOSE_MIN} =="
if ! command -v docker >/dev/null 2>&1; then
    echo "docker absent — installing via get.docker.com (then re-checking the window)"
    curl -fsSL https://get.docker.com | "${SUDO[@]}" sh
fi
# `|| true` keeps the failing substitution from aborting under set -e
# before the guard below can report it (2>/dev/null would otherwise
# swallow the reason: stopped daemon, or socket not readable by caller).
DOCKER_VER=$(docker version --format '{{.Server.Version}}' 2>/dev/null || true)
[ -n "$DOCKER_VER" ] || fail "docker daemon not reachable — is dockerd running, and are you root (or in the docker group)? (04: single-user VM, run as root)"
ver_at_least() { [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$2" ]; }
ver_at_least "$DOCKER_VER" "$DOCKER_MIN" \
    || fail "Docker Engine $DOCKER_VER < floor $DOCKER_MIN (below the VSS floor the stack will not start — 10 c8)"
ver_at_least "$DOCKER_MAX" "$DOCKER_VER" \
    || fail "Docker Engine $DOCKER_VER >= $DOCKER_MAX — newer Docker breaks NGC pulls (10 c8); the template must carry a version inside the window"
# Keep docker's own stderr (loud failures, per the header): the plugin can be
# installed per-user (~/.docker/cli-plugins) and still be invisible here —
# under sudo $HOME is /root, so a plugin installed for another user does not
# follow the user.
COMPOSE_RAW=$(docker compose version --short 2>&1 || true)
COMPOSE_VER=$(printf '%s\n' "$COMPOSE_RAW" | head -1 | sed 's/^v//')
printf '%s\n' "$COMPOSE_VER" | grep -qE '^[0-9]+(\.[0-9]+)+' \
    || fail "docker compose plugin not visible to '$(id -un)' — docker said: $(printf '%s\n' "$COMPOSE_RAW" | head -1) (plugin only present in another user's ~/.docker/cli-plugins? install it system-wide: apt install docker-compose-v2 — 10 c8)"
ver_at_least "$COMPOSE_VER" "$COMPOSE_MIN" \
    || fail "Docker Compose $COMPOSE_VER < floor $COMPOSE_MIN (10 c8)"
echo "docker: $DOCKER_VER, compose: $COMPOSE_VER"
log "- docker engine: $DOCKER_VER (window [${DOCKER_MIN}, ${DOCKER_MAX}))"
log "- docker compose: $COMPOSE_VER (>= ${COMPOSE_MIN})"

# ---- 3. NVIDIA Container Toolkit ------------------------------------------
echo "== 3/8 NVIDIA Container Toolkit >= ${CTK_MIN} =="
if ! command -v nvidia-ctk >/dev/null 2>&1; then
    echo "toolkit absent — apt install nvidia-container-toolkit"
    "${SUDO[@]}" apt-get update -qq
    "${SUDO[@]}" apt-get install -y -qq nvidia-container-toolkit
fi
CTK_VER=$(nvidia-ctk --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
[ -n "$CTK_VER" ] || fail "cannot parse nvidia-ctk version"
ver_at_least "$CTK_VER" "$CTK_MIN" \
    || fail "NVIDIA Container Toolkit $CTK_VER < floor $CTK_MIN (09)"
"${SUDO[@]}" nvidia-ctk runtime configure --runtime=docker
echo "toolkit: $CTK_VER"
log "- nvidia container toolkit: $CTK_VER (docker runtime configured)"

# ---- 4. daemon.json: cgroupfs + default-shm-size 32g -----------------------
echo "== 4/8 Docker daemon.json (cgroupfs, default-shm-size 32g) =="
"${SUDO[@]}" python3 - <<'PY'
import json, os
path = "/etc/docker/daemon.json"
cfg = {}
if os.path.exists(path):
    with open(path) as f:
        cfg = json.load(f)
changed = []
opts = cfg.get("exec-opts", [])
if "native.cgroupdriver=cgroupfs" not in opts:
    opts.append("native.cgroupdriver=cgroupfs")
    cfg["exec-opts"] = opts
    changed.append("exec-opts += native.cgroupdriver=cgroupfs")
if cfg.get("default-shm-size") != "32g":
    cfg["default-shm-size"] = "32g"
    changed.append("default-shm-size = 32g")
if changed:
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("changed: " + "; ".join(changed))
else:
    print("daemon.json already carries cgroupfs + 32g shm")
PY
"${SUDO[@]}" systemctl restart docker
CGROUP_DRIVER=$(docker info --format '{{.CgroupDriver}}' 2>/dev/null || true)
[ "$CGROUP_DRIVER" = "cgroupfs" ] \
    || fail "daemon cgroup driver is $CGROUP_DRIVER, want cgroupfs (VSS prerequisite — 10 c6)"
SHM_GIB=$(python3 - <<'PY'
import json
print(json.load(open("/etc/docker/daemon.json")).get("default-shm-size", ""))
PY
)
[ "$SHM_GIB" = "32g" ] || fail "daemon default-shm-size is '$SHM_GIB', want 32g (10 c2)"
echo "cgroup driver: $CGROUP_DRIVER; default-shm-size: $SHM_GIB"
log "- docker daemon: cgroupfs, default-shm-size 32g (10 c2/c6)"

# ---- 5. sysctl (10 constraint 3 — Elasticsearch refuses to start otherwise)
echo "== 5/8 sysctl /etc/sysctl.d/99-vss.conf =="
"${SUDO[@]}" tee /etc/sysctl.d/99-vss.conf >/dev/null <<'EOF'
# 99-vss.conf — 10 constraint 3 (Elasticsearch refuses to start without
# vm.max_map_count; the build document's failure modes).
vm.max_map_count = 262144
fs.file-max = 2097152
net.core.somaxconn = 4096
EOF
"${SUDO[@]}" sysctl --system >/dev/null
for kv in "vm.max_map_count 262144" "fs.file-max 2097152" "net.core.somaxconn 4096"; do
    set -- $kv
    GOT=$(sysctl -n "$1")
    [ "$GOT" = "$2" ] || fail "sysctl $1 is $GOT, want $2 (10 c3)"
    echo "$1 = $GOT"
done
log "- sysctl: vm.max_map_count=262144, fs.file-max=2097152, net.core.somaxconn=4096 (10 c3)"

# ---- 6. Node.js 20 (09 — NemoClaw host requirement) ------------------------
echo "== 6/8 Node.js ${NODE_WANT}.x =="
NODE_VER=""
if command -v node >/dev/null 2>&1; then
    NODE_VER=$(node --version | sed 's/^v//')
fi
NODE_MAJOR="${NODE_VER%%.*}"
if [ "$NODE_MAJOR" != "$NODE_WANT" ]; then
    echo "node ${NODE_VER:-absent} -> installing NodeSource setup_20.x"
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_WANT}.x" | "${SUDO[@]}" bash -
    # Verify the repo actually registered ${NODE_WANT}.x as the candidate: on
    # an apt failure (e.g. broken dpkg) setup_*.x bails mid-script and
    # 'apt-get install nodejs' would silently install the distro's node (18
    # on noble) — exactly the silent substitution 09 forbids.
    NODE_CANDIDATE="$(apt-cache policy nodejs 2>/dev/null | sed -n 's/^ Candidate: //p')"
    [ "${NODE_CANDIDATE%%.*}" = "$NODE_WANT" ] \
        || fail "NodeSource repo did not register nodejs ${NODE_WANT}.x (candidate: ${NODE_CANDIDATE:-none}) — setup_${NODE_WANT}.x failed early; fix the root cause (see its output above; dpkg --audit) and re-run"
    "${SUDO[@]}" apt-get install -y -qq nodejs
    NODE_VER=$(node --version | sed 's/^v//')
    NODE_MAJOR="${NODE_VER%%.*}"
fi
[ "$NODE_MAJOR" = "$NODE_WANT" ] \
    || fail "node is ${NODE_VER}, want ${NODE_WANT}.x (09)"
echo "node: v${NODE_VER}"
log "- node.js: v${NODE_VER} (09: Node 20.x host requirement)"
log "  (prep note: the v3.2.1 init_nemoclaw.sh installer needs Node 22+ and"
log "   bootstraps it via nvm when 20.x is the system node — the node the"
log "   installer actually runs on is recorded by 40-nemoclaw.sh)"

# The dev test contract (03/05: scripts/test/run-dev-tests.sh) bootstraps its
# pinned .venv with plain `python3 -m venv` — that needs the distro's
# python3-venv package, which is NOT installed by default on a fresh noble
# VM (dry-run 2026-09-10: "ensurepip is not available").
if ! dpkg -s python3.12-venv >/dev/null 2>&1; then
    echo "installing python3.12-venv (test contract dependency)"
    "${SUDO[@]}" apt-get install -y -qq python3.12-venv
fi
dpkg -s python3.12-venv >/dev/null 2>&1 \
    || fail "python3.12-venv could not be installed (the dev test contract needs python3 -m venv — 03)"
echo "python3.12-venv: present"
log "- python3.12-venv: present (03: the dev test contract bootstraps its .venv with python3 -m venv)"

# ---- 7. /data directories (09 artifacts) -----------------------------------
echo "== 7/8 /data directories =="
"${SUDO[@]}" mkdir -p /data/vss-apps-data /data/corpus /data/video /data/nim-cache
# vendor-mandated tolerance accepted in 04: chmod 777 on the VSS data_log dir
# (single-user VM, demo data only).
"${SUDO[@]}" mkdir -p /data/vss-apps-data/data_log
"${SUDO[@]}" chmod -R 777 /data/vss-apps-data/data_log
for d in /data/vss-apps-data /data/corpus /data/video /data/nim-cache; do
    [ -d "$d" ] || fail "mkdir $d failed"
    echo "ok: $d"
done
log "- /data: vss-apps-data (+data_log 777 per 04), corpus, video, nim-cache"

# ---- 8. nvcr.io login (04: --password-stdin; never a CLI argument) ---------
echo "== 8/8 nvcr.io login from $LAB_ENV =="
[ -f "$LAB_ENV" ] || fail "lab.env not found at $LAB_ENV — the instructor injects NGC_CLI_API_KEY, NVIDIA_API_KEY, SHARED_API_KEY, SHARED_ENDPOINT_URL there before prep (04; gitignored location)"
# A Windows-line-ending file poisons every sourced value with a trailing CR:
# NGC answers 401 to the login (the value looks present and non-empty), and
# SHARED_ENDPOINT_URL would break the shim later. Catch it before sourcing.
# (grep polarity: 0 = CR found = the bad case, hence && not ||.)
if grep -q $'\r' "$LAB_ENV"; then
    fail "$LAB_ENV has Windows (CRLF) line endings — convert to LF and re-run: sed -i 's/\r$//' $LAB_ENV"
fi
set -a
# shellcheck disable=SC1090
. "$LAB_ENV"
set +a
for v in NGC_CLI_API_KEY NVIDIA_API_KEY SHARED_API_KEY SHARED_ENDPOINT_URL; do
    eval "val=\${$v:-}"
    [ -n "$val" ] || fail "$v is empty in $LAB_ENV (instructor must fill lab.env before prep — 04)"
    case $val in
        *[[:space:]]*) fail "$v in $LAB_ENV contains whitespace (a pasted newline or stray space) — re-enter that value on one line and re-run" ;;
    esac
done
case $NGC_CLI_API_KEY in
    nvapi-*) : ;;
    *) echo "00-host-prep: NOTE — NGC_CLI_API_KEY does not start with 'nvapi-'; NGC API keys (org.nvidia.com) do. If the login fails below, check this is the NGC key, not the build.nvidia.com key." ;;
esac
if ! printf '%s' "$NGC_CLI_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin >/dev/null; then
    fail "nvcr.io login failed (docker's own error above is the daemon's). If it says 'unauthorized': NGC rejected NGC_CLI_API_KEY — it must be the NGC API key (starts with nvapi-, created at org.nvidia.com) that still exists: not the build.nvidia.com key, not a deleted/rotated one. The CRLF/whitespace checks above already rule out file corruption. Verify without docker, value never printed (04): source $LAB_ENV, then: curl -s -o /dev/null -w '%{http_code}\n' -u \"\$oauthtoken:\$NGC_CLI_API_KEY\" https://nvcr.io/v2/ — 200 means the key is valid (then it is the daemon's network/proxy path to nvcr.io); 401 means NGC rejects the key. If docker said something else (proxy, timeout): fix the daemon's egress to nvcr.io."
fi
echo "nvcr.io login ok (key never printed — 04)"
log "- nvcr.io: logged in from $LAB_ENV (--password-stdin; values not logged — 04)"

echo "00-host-prep: PASS — recorded in $(basename "$PREP_LOG")"
