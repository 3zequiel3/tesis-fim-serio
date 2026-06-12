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
CONFIG_DEST="/etc/fim-agent/config.yaml"
CONFIG_EXAMPLE="${AGENT_SRC}/deploy/config.yaml.example"

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

# --- 8.5: Install and enable systemd unit ---
cp "${AGENT_SRC}/deploy/fim-agent.service" "${SYSTEMD_UNIT}"
chmod 0644 "${SYSTEMD_UNIT}"
systemctl daemon-reload
systemctl enable fim-agent
echo "[fim-agent] Installed and enabled fim-agent.service"

# --- 8.6: Copy example config only if no config exists ---
if [ ! -f "${CONFIG_DEST}" ]; then
    cp "${CONFIG_EXAMPLE}" "${CONFIG_DEST}"
    chmod 0640 "${CONFIG_DEST}"
    echo "[fim-agent] Copied example config to ${CONFIG_DEST} — edit before starting"
else
    echo "[fim-agent] Config already exists at ${CONFIG_DEST}, skipping"
fi

# --- 8.7: Apply final ownership ---
chown -R "${AGENT_USER}:${AGENT_USER}" \
    /var/lib/fim-agent \
    /var/log/fim-agent \
    /etc/fim-agent \
    "${AGENT_DEST}"
echo "[fim-agent] Applied chown -R ${AGENT_USER} to all agent directories"

echo ""
echo "[fim-agent] Installation complete."
echo "  Edit ${CONFIG_DEST} with your agent_id and watch_paths, then run:"
echo "    systemctl start fim-agent"
echo "    systemctl status fim-agent"
