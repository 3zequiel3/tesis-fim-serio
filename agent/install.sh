#!/usr/bin/env bash
# install.sh — FIM Agent installation script (D56/RN-150, design D-7 of
# vps-deployment-readiness).
#
# Thin bash: only what requires root and systemd lives here (user/directory
# creation, the venv, the unit file, daemon-reload, enable/start/restart, and
# the ownership rules from change 41, D36/RN-130). Argument parsing, prompts,
# the CA fingerprint check, config.yaml rendering, the bootstrap secret write
# and the network scope check live in agent/installer.py — pure functions
# testable with pytest and no root privileges (same split agent/deployment.py
# already uses for the systemd drop-in).
#
# This script forwards its arguments to installer.py unmodified — no secret
# value ever sits in a shell variable or shows up in `ps`. It DOES read two
# non-secret things out of "$@" before forwarding (D56/RN-150 findings
# 14.1/14.2, revised 2026-09-15 after the VPS acceptance run): `--python
# <path>` picks the interpreter used to create the venv, and a relative
# --ca-cert/--bootstrap-secret-file path is rewritten to an absolute one
# (resolved against the directory install.sh was invoked from) before the
# apply/check phases `cd` into ${AGENT_DEST} — everything else, the bootstrap
# secret above all, still passes through untouched. See agent/installer.py
# --help (via its subcommands) and
# openspec/changes/vps-deployment-readiness/design.md (D-7) for the full
# flag/env-var reference.
#
# Idempotent: safe to re-run. Re-running REPLACES the installed code (never
# merges into it — a previous bug nested it at agent/agent/) and never
# overwrites an operator-edited config.yaml/env unless --reconfigure is
# passed.
#
# Must run as root, from the repository root, e.g.:
#   sudo bash agent/install.sh --non-interactive \
#     --server-host 203.0.113.10 --agent-id web-01 --watch-path /srv/app \
#     --ca-cert ./fim-ca.pem --ca-fingerprint <fingerprint> \
#     --bootstrap-secret-file ./secret
set -euo pipefail

AGENT_USER="fim-agent"
AGENT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DEST="/opt/fim-agent"
AGENT_LIVE="${AGENT_DEST}/agent"
AGENT_STAGING="${AGENT_DEST}/agent.staging"
AGENT_PREVIOUS="${AGENT_DEST}/agent.previous"
VENV_DIR="${AGENT_DEST}/venv"
SYSTEMD_UNIT="/etc/systemd/system/fim-agent.service"
SYSTEMD_DROPIN_DIR="/etc/systemd/system/fim-agent.service.d"
SYSTEMD_DROPIN="${SYSTEMD_DROPIN_DIR}/10-watchpaths.conf"
CONFIG_DEST="/etc/fim-agent/config.yaml"
ENV_DEST="/etc/fim-agent/env"
CA_CERT_DEST="/etc/fim-agent/certs/ca.pem"
AGENT_CERT_PATH="/var/lib/fim-agent/certs/agent-cert.pem"
REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=13

echo "[fim-agent] Installing FIM Agent from ${AGENT_SRC}"

# --- Capture state BEFORE any change: needed for the enable/start/restart
# decision at the very end (D-7 step 10), and for the version check and path
# resolution below (D56/RN-150 findings 14.1/14.2). ---
WAS_ACTIVE=false
if systemctl is-active --quiet fim-agent 2>/dev/null; then
    WAS_ACTIVE=true
fi
ENV_EXISTED_BEFORE=false
if [ -f "${ENV_DEST}" ]; then
    ENV_EXISTED_BEFORE=true
fi

# The directory install.sh was invoked from — captured before this script (or
# any subshell it spawns) ever `cd`s anywhere, so a relative --ca-cert or
# --bootstrap-secret-file always resolves against it, even in the apply/check
# phases below that `cd "${AGENT_DEST}"` first (finding 14.2; previously
# those two phases silently resolved relative paths against
# /opt/fim-agent instead of the operator's own working directory).
INVOCATION_DIR="$(pwd)"

_resolve_relative() {
    # $1: a path that may be relative. Prints it unchanged if absolute,
    # otherwise prefixed with INVOCATION_DIR.
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *) printf '%s\n' "${INVOCATION_DIR}/$1" ;;
    esac
}

RECONFIGURE=false
PYTHON_BIN="${FIM_AGENT_PYTHON:-python3}"
RESOLVED_ARGS=()
prev_flag=""
for arg in "$@"; do
    case "${prev_flag}" in
        --ca-cert|--bootstrap-secret-file)
            RESOLVED_ARGS+=("$(_resolve_relative "${arg}")")
            prev_flag=""
            continue
            ;;
        --python)
            PYTHON_BIN="${arg}"
            RESOLVED_ARGS+=("${arg}")
            prev_flag=""
            continue
            ;;
    esac
    case "${arg}" in
        --reconfigure)
            RECONFIGURE=true
            ;;
        --ca-cert=*)
            RESOLVED_ARGS+=("--ca-cert=$(_resolve_relative "${arg#--ca-cert=}")")
            prev_flag=""
            continue
            ;;
        --bootstrap-secret-file=*)
            RESOLVED_ARGS+=("--bootstrap-secret-file=$(_resolve_relative "${arg#--bootstrap-secret-file=}")")
            prev_flag=""
            continue
            ;;
        --python=*)
            PYTHON_BIN="${arg#--python=}"
            ;;
    esac
    RESOLVED_ARGS+=("${arg}")
    prev_flag="${arg}"
done

# --- Create fim-agent user if not exists (unchanged, change 41) ---
if ! id "${AGENT_USER}" &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin "${AGENT_USER}"
    echo "[fim-agent] Created system user: ${AGENT_USER}"
else
    echo "[fim-agent] User ${AGENT_USER} already exists, skipping"
fi

# --- Create /var/lib/fim-agent/ directory tree (unchanged, change 41) ---
# 'discarded' (Change 42, D37/RN-131): terminal local destination for events
# that exhausted the retry ceiling or received a terminal event_nack.
for dir in baseline quarantine queue journal secrets certs discarded; do
    mkdir -p "/var/lib/fim-agent/${dir}"
    chmod 0700 "/var/lib/fim-agent/${dir}"
done
chmod 0700 /var/lib/fim-agent
echo "[fim-agent] Created /var/lib/fim-agent/ layout with 0700"

mkdir -p /var/log/fim-agent
chmod 0750 /var/log/fim-agent

mkdir -p /etc/fim-agent
chmod 0750 /etc/fim-agent
echo "[fim-agent] Created /var/log/fim-agent/ and /etc/fim-agent/"

# --- D-7 step 2: create venv (first run only) and stage the new code into a
# side directory. Never copy straight into agent/: cp -r into an existing
# directory nests the source one level deeper (the change-41 follow-up this
# change resolves) and would leave stale files from a previous version around.
mkdir -p "${AGENT_DEST}"
if [ ! -x "${VENV_DIR}/bin/python" ]; then
    # D56/RN-150 finding 14.1: validate the interpreter version BEFORE
    # creating the venv, not deep inside `pip install` while building
    # pydantic-core — PyO3 (its build backend, as of this change's pinned
    # dependencies) caps out at Python 3.13, so a newer system default (e.g.
    # Python 3.14 on Ubuntu 26.04) must be rejected here with an actionable
    # message, not a wall of a build failure. Only runs when a venv is about
    # to be CREATED: reinstalling on top of an already-created venv (e.g.
    # pre-created with `uv python install 3.13`) never re-validates the
    # system default, since install.sh will not touch it.
    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
        echo "[fim-agent] ERROR: Python interpreter '${PYTHON_BIN}' not found." >&2
        echo "  Install Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} (e.g. 'uv python install ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}') or pass --python <path>." >&2
        exit 1
    fi
    PYTHON_VERSION="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    PYTHON_MAJOR="${PYTHON_VERSION%%.*}"
    PYTHON_MINOR="${PYTHON_VERSION##*.}"
    if [ "${PYTHON_MAJOR}" -ne "${REQUIRED_PYTHON_MAJOR}" ] || [ "${PYTHON_MINOR}" -ne "${REQUIRED_PYTHON_MINOR}" ]; then
        echo "[fim-agent] ERROR: ${PYTHON_BIN} is Python ${PYTHON_VERSION}; the FIM Agent requires exactly Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}." >&2
        echo "  Install it with 'uv python install ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}' and re-run with" >&2
        echo "  '--python <path-to-a-${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}-interpreter>'." >&2
        exit 1
    fi
    echo "[fim-agent] Using ${PYTHON_BIN} (Python ${PYTHON_VERSION})"

    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    echo "[fim-agent] Created venv at ${VENV_DIR}"
fi

rm -rf "${AGENT_STAGING}"
cp -r "${AGENT_SRC}" "${AGENT_STAGING}"

"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${AGENT_STAGING}/requirements.txt"
echo "[fim-agent] Installed Python dependencies into ${VENV_DIR}"

# --- D-7 step 3: `installer.py plan` — resolve and validate every input
# (precedence, watch paths, CA fingerprint, bootstrap secret) against the
# CODE BEING INSTALLED, before touching anything under /etc/fim-agent or
# replacing the currently-installed (working) code. A bad fingerprint or an
# invalid watch path aborts here and leaves the host exactly as it was.
#
# `agent.staging` cannot be imported as package `agent` by name, so a
# throwaway PYTHONPATH entry symlinks it under the right name for this one
# invocation only.
PLAN_PYTHONPATH_DIR="$(mktemp -d)"
ln -s "${AGENT_STAGING}" "${PLAN_PYTHONPATH_DIR}/agent"
PYTHONPATH="${PLAN_PYTHONPATH_DIR}" "${VENV_DIR}/bin/python" -m agent.installer plan "${RESOLVED_ARGS[@]}"
rm -rf "${PLAN_PYTHONPATH_DIR}"
echo "[fim-agent] Plan validated"

# --- D-7 step 4: replace the installed code (never merge). ---
if [ -d "${AGENT_LIVE}" ]; then
    rm -rf "${AGENT_PREVIOUS}"
    mv "${AGENT_LIVE}" "${AGENT_PREVIOUS}"
fi
mv "${AGENT_STAGING}" "${AGENT_LIVE}"
rm -rf "${AGENT_PREVIOUS}"
echo "[fim-agent] Replaced installed code at ${AGENT_LIVE}"

# --- D-7 step 5: install systemd unit (base unit left byte-identical, D36/RN-130 D-2) ---
cp "${AGENT_LIVE}/deploy/fim-agent.service" "${SYSTEMD_UNIT}"
chmod 0644 "${SYSTEMD_UNIT}"
echo "[fim-agent] Installed fim-agent.service"

# --- D-7 step 6: `installer.py apply` — writes config.yaml (only if absent
# or --reconfigure, with a .bak-<timestamp> copy), the verified ca.pem, and
# env with FIM_BOOTSTRAP_SECRET (0600 root:root). Runs against the
# NOW-INSTALLED code, same WorkingDirectory/import as ExecStart. ---
(
    cd "${AGENT_DEST}"
    "${VENV_DIR}/bin/python" -m agent.installer apply "${RESOLVED_ARGS[@]}"
)
echo "[fim-agent] Applied configuration"

# --- D-7 step 7: generate the ReadWritePaths drop-in from the installed
# config (D36/RN-130 D-2) — must run AFTER config.yaml exists and BEFORE
# daemon-reload, since the reload has to observe both the unit and the
# drop-in together. Rejects malformed paths (agent/deployment.py) and aborts
# the install (set -euo pipefail) rather than installing a truncated drop-in.
mkdir -p "${SYSTEMD_DROPIN_DIR}"
(
    cd "${AGENT_DEST}"
    "${VENV_DIR}/bin/python" -m agent.deployment \
        --config "${CONFIG_DEST}" \
        --output "${SYSTEMD_DROPIN}"
)
chmod 0644 "${SYSTEMD_DROPIN}"
echo "[fim-agent] Generated ${SYSTEMD_DROPIN} from ${CONFIG_DEST}"

# --- D-7 step 8: reload systemd (enable/start/restart come after the scope
# check below). ---
systemctl daemon-reload
echo "[fim-agent] Reloaded systemd"

# --- D-7 step 9: `installer.py check` — verifies 8444 and 6380 are
# reachable, TLS-trusted, and cover the configured host before the service is
# ever enabled. ---
CHECK_STATUS=0
(
    cd "${AGENT_DEST}"
    "${VENV_DIR}/bin/python" -m agent.installer check "${RESOLVED_ARGS[@]}"
) || CHECK_STATUS=$?

# --- D-7 step 11: apply final ownership regardless of the check outcome, so
# the host is left in a consistent state either way.
#
# The service process holds CAP_DAC_OVERRIDE and can still write under
# /opt/fim-agent and /etc/fim-agent — update_config needs to write
# config.yaml. What root ownership removes is the OTHER vector: a shell
# obtained as the fim-agent uid OUTSIDE the service process holds no ambient
# capabilities and can no longer rewrite the code systemd executes with
# CAP_SYS_ADMIN on the next restart. A recursive chown to the service user
# collapses that separation into a one-step privilege escalation — this is
# why /opt/fim-agent and /etc/fim-agent are NOT chowned to fim-agent.
chown -R root:root "${AGENT_DEST}"
find "${AGENT_DEST}" -type d -exec chmod 0755 {} +
# /etc/fim-agent is addressed file-by-file (not -R) so config.yaml, env and
# certs/ca.pem each keep the distinct owner/mode the table above requires.
chown root:"${AGENT_USER}" /etc/fim-agent
chmod 0750 /etc/fim-agent
if [ -f "${CONFIG_DEST}" ]; then
    chown root:"${AGENT_USER}" "${CONFIG_DEST}"
    chmod 0640 "${CONFIG_DEST}"
fi
if [ -f "${ENV_DEST}" ]; then
    chown root:root "${ENV_DEST}"
    chmod 0600 "${ENV_DEST}"
fi
if [ -f "${CA_CERT_DEST}" ]; then
    chown root:root "${CA_CERT_DEST}"
    chmod 0644 "${CA_CERT_DEST}"
fi
chown -R "${AGENT_USER}:${AGENT_USER}" /var/lib/fim-agent /var/log/fim-agent
echo "[fim-agent] Applied ownership: /opt+/etc root-owned, /var/lib+/var/log owned by ${AGENT_USER}"

if [ "${CHECK_STATUS}" -ne 0 ]; then
    echo "" >&2
    echo "[fim-agent] Scope check failed (see diagnostics above) — service NOT enabled." >&2
    exit 3
fi

# --- D-7 step 10: enable, then start or restart. ---
systemctl enable fim-agent
echo "[fim-agent] Enabled fim-agent.service"

ENV_WRITTEN=false
if [ "${ENV_EXISTED_BEFORE}" = false ] || [ "${RECONFIGURE}" = true ]; then
    ENV_WRITTEN=true
fi

if [ "${WAS_ACTIVE}" = true ]; then
    systemctl restart fim-agent
    echo "[fim-agent] Restarted fim-agent.service to load the new code"
elif [ "${ENV_WRITTEN}" = true ] && [ ! -f "${AGENT_CERT_PATH}" ]; then
    systemctl start fim-agent
    echo "[fim-agent] Started fim-agent.service (bootstrap secret provided, no certificate yet)"
else
    echo "[fim-agent] Service enabled but not started — run 'systemctl start fim-agent' when ready"
fi

echo ""
echo "[fim-agent] Installation complete."
echo "  systemctl status fim-agent"
