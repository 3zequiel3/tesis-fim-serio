#!/usr/bin/env bash
# install.sh — FIM Agent installation script
# Idempotent: safe to run multiple times.
# Must be run as root. Run from the repository root:
#   sudo bash agent/install.sh
set -euo pipefail

AGENT_USER="fim-agent"
AGENT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DEST="/opt/fim-agent"
VENV_DIR="${AGENT_DEST}/venv"
SYSTEMD_UNIT="/etc/systemd/system/fim-agent.service"
SYSTEMD_DROPIN_DIR="/etc/systemd/system/fim-agent.service.d"
SYSTEMD_DROPIN="${SYSTEMD_DROPIN_DIR}/10-watchpaths.conf"
CONFIG_DEST="/etc/fim-agent/config.yaml"
CONFIG_EXAMPLE="${AGENT_SRC}/deploy/config.yaml.example"
ENV_DEST="/etc/fim-agent/env"
ENV_EXAMPLE="${AGENT_SRC}/deploy/env.example"

echo "[fim-agent] Installing FIM Agent from ${AGENT_SRC}"

# --- 8.1: Create fim-agent user if not exists ---
if ! id "${AGENT_USER}" &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin "${AGENT_USER}"
    echo "[fim-agent] Created system user: ${AGENT_USER}"
else
    echo "[fim-agent] User ${AGENT_USER} already exists, skipping"
fi

# --- 8.2: Create /var/lib/fim-agent/ directory tree ---
for dir in baseline quarantine queue journal secrets certs; do
    mkdir -p "/var/lib/fim-agent/${dir}"
    chmod 0700 "/var/lib/fim-agent/${dir}"
done
chmod 0700 /var/lib/fim-agent
echo "[fim-agent] Created /var/lib/fim-agent/ layout with 0700"

# --- 8.3: Create log and config directories ---
mkdir -p /var/log/fim-agent
chmod 0750 /var/log/fim-agent

mkdir -p /etc/fim-agent
chmod 0750 /etc/fim-agent
echo "[fim-agent] Created /var/log/fim-agent/ and /etc/fim-agent/"

# --- 8.4: Create venv and install dependencies ---
mkdir -p "${AGENT_DEST}"
if [ ! -x "${VENV_DIR}/bin/python" ]; then
    python3 -m venv "${VENV_DIR}"
    echo "[fim-agent] Created venv at ${VENV_DIR}"
fi

# Copy agent source to destination
cp -r "${AGENT_SRC}" "${AGENT_DEST}/agent"

"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${AGENT_SRC}/requirements.txt"
echo "[fim-agent] Installed Python dependencies into ${VENV_DIR}"

# --- 8.5: Install systemd unit (base unit left byte-identical, D36/RN-130 D-2) ---
cp "${AGENT_SRC}/deploy/fim-agent.service" "${SYSTEMD_UNIT}"
chmod 0644 "${SYSTEMD_UNIT}"
echo "[fim-agent] Installed fim-agent.service"

# --- 8.6: Copy example config only if no config exists ---
if [ ! -f "${CONFIG_DEST}" ]; then
    cp "${CONFIG_EXAMPLE}" "${CONFIG_DEST}"
    chmod 0640 "${CONFIG_DEST}"
    echo "[fim-agent] Copied example config to ${CONFIG_DEST} — edit before starting"
else
    echo "[fim-agent] Config already exists at ${CONFIG_DEST}, skipping"
fi

# --- 8.6.5: Install environment file template only if it does not exist ---
# (D36/RN-130 D-10) — the bootstrap secret is single-use, expected to be
# removed after first boot; installer never overwrites an operator-edited file.
if [ ! -f "${ENV_DEST}" ]; then
    cp "${ENV_EXAMPLE}" "${ENV_DEST}"
    chmod 0600 "${ENV_DEST}"
    chown root:root "${ENV_DEST}"
    echo "[fim-agent] Installed environment file template at ${ENV_DEST}"
else
    echo "[fim-agent] Environment file already exists at ${ENV_DEST}, skipping"
fi

# --- 8.6.6: Generate the ReadWritePaths drop-in from the installed config ---
# (D36/RN-130 D-2) — must run AFTER the config exists and BEFORE daemon-reload,
# since the reload has to observe both the unit and the drop-in together.
# Rejects malformed paths (agent/deployment.py) and aborts the install
# (set -euo pipefail) rather than installing a truncated drop-in.
mkdir -p "${SYSTEMD_DROPIN_DIR}"
# Se invoca desde AGENT_DEST — mismo WorkingDirectory e importación que usa
# ExecStart (`python -m agent ...`), para que `agent.deployment` resuelva
# igual en ambos casos.
(
    cd "${AGENT_DEST}"
    "${VENV_DIR}/bin/python" -m agent.deployment \
        --config "${CONFIG_DEST}" \
        --output "${SYSTEMD_DROPIN}"
)
chmod 0644 "${SYSTEMD_DROPIN}"
echo "[fim-agent] Generated ${SYSTEMD_DROPIN} from ${CONFIG_DEST}"

# --- 8.7: Reload systemd and enable the service ---
systemctl daemon-reload
systemctl enable fim-agent
echo "[fim-agent] Reloaded systemd and enabled fim-agent.service"

# --- 8.8: Apply final ownership (D36/RN-130 D-11) ---
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
# /etc/fim-agent is addressed file-by-file (not -R) so config.yaml and env
# each keep the distinct owner/mode the table above requires.
chown root:"${AGENT_USER}" /etc/fim-agent
chmod 0750 /etc/fim-agent
chown root:"${AGENT_USER}" "${CONFIG_DEST}"
chmod 0640 "${CONFIG_DEST}"
chown root:root "${ENV_DEST}"
chmod 0600 "${ENV_DEST}"
chown -R "${AGENT_USER}:${AGENT_USER}" /var/lib/fim-agent /var/log/fim-agent
echo "[fim-agent] Applied ownership: /opt+/etc root-owned, /var/lib+/var/log owned by ${AGENT_USER}"

echo ""
echo "[fim-agent] Installation complete."
echo "  Edit ${CONFIG_DEST} with your agent_id and watch_paths, then run:"
echo "    sudo bash agent/install.sh   # re-run to regenerate the watch_paths drop-in"
echo "    systemctl start fim-agent"
echo "    systemctl status fim-agent"
