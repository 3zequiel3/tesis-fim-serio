#!/bin/sh
# FIM Platform — n8n container entrypoint: workflow + credential provisioning
# (D44/RN-138, D58/RN-152 revised, D-6 of the vps-deployment-readiness design)
# followed by a hand-off to the real `n8n` process.
#
# *(Revised 2026-09-15 after the VPS acceptance run, finding 14.5)* This used
# to be a separate one-shot `n8n-provision` service that `n8n` depended on
# with `service_completed_successfully`. That worked for a clean `up`, but a
# SECOND `docker compose up -d` with `n8n` already healthy re-ran the one-shot
# service anyway (Compose recreates a service whose desired state is not
# already "up", and an exited one-shot container never is) — silently
# re-publishing the workflows against an `n8n` process that was already
# running. `n8n publish:workflow` only takes effect for the NEXT `n8n start`
# — it explicitly warns "Please restart n8n for changes to take effect if n8n
# is currently running" — so the webhook was left unregistered (POST
# /webhook/fim-alert -> 404) until someone noticed and ran `restart n8n` by
# hand. Running this INSIDE the `n8n` container's own entrypoint, before `n8n`
# itself starts, removes the race entirely: as long as `n8n`'s desired state
# (image + environment + mounts) does not change, Compose leaves the
# container alone on a second `up -d` and this script never runs again while
# `n8n` is already serving traffic.
#
# Steps, in order:
#   1. Render every `n8n/workflows/*.json` file: replace each
#      `__FIM_ENV_<NAME>__` token with the current `$<NAME>` value (render.js;
#      see its module docstring for the exact substitution contract).
#   2. Import each rendered workflow by its stable `id` (import:workflow
#      overwrites the existing DB row rather than duplicating it).
#   3. Import credentials for every channel listed in `N8N_FIM_CHANNELS`
#      (comma-separated; recognized tokens: email, slack, jira, linear).
#      import:credentials is unconditional for the whole file, so only
#      credentials for ENABLED channels are written into it — an unconfigured
#      channel's secret variables are simply never read.
#   4. Publish every expected workflow id.
#   5. Verify with `n8n list:workflow --active=true --onlyId` that every
#      expected id is active; exit non-zero naming the first one that is not
#      — this is a plain DB read via the n8n CLI, so it works whether or not
#      the long-lived n8n process has started yet (it has not, at this
#      point).
#   6. `exec n8n "$@"` — hand off to the real n8n process, same as the
#      image's own `/docker-entrypoint.sh` (`exec n8n "$@"` / `exec n8n`).
#      Since this replaces the current process image rather than forking, the
#      long-lived n8n process stays tini's direct child, exactly as it would
#      under the stock entrypoint — signal forwarding and zombie reaping are
#      unaffected (docker-compose.yml keeps `entrypoint: ["tini", "--",
#      "/bin/sh", "/provision/entrypoint.sh"]`, i.e. tini still owns pid 1).
#
# A failure at any of steps 1-5 aborts before publishing anything further and
# before n8n ever starts.
set -eu

WORKFLOWS_DIR=${WORKFLOWS_DIR:-/workflows}
RENDER_JS=${RENDER_JS:-/provision/render.js}
RENDERED_DIR=$(mktemp -d)
trap 'rm -rf "$RENDERED_DIR"' EXIT

# Stable ids — MUST match the `id` field of the corresponding file in
# n8n/workflows/. Kept here (not derived) so a missing/renamed file fails
# loudly with a clear diagnostic rather than silently skipping verification.
ROUTER_ID=2c8651c9-e8dc-45ef-88af-c805760ff919
EMAIL_ID=9d42f98a-d16c-4224-9c9b-8c7a8593bff8
SLACK_ID=00100d40-0e73-4762-9b79-9a030f7b46f7
TICKET_ID=dc8458ed-b9a2-4c05-bf95-824f068abf7f

log() { printf 'entrypoint.sh: %s\n' "$1"; }
fail() { printf 'entrypoint.sh: ERROR: %s\n' "$1" >&2; exit 1; }

# ── 1. Render ─────────────────────────────────────────────────────────────
[ -d "$WORKFLOWS_DIR" ] || fail "workflows directory not found: $WORKFLOWS_DIR"
found_any=0
for src in "$WORKFLOWS_DIR"/*.json; do
  [ -e "$src" ] || continue
  found_any=1
  name=$(basename "$src")
  log "rendering $name"
  node "$RENDER_JS" "$src" "$RENDERED_DIR/$name"
done
[ "$found_any" = 1 ] || fail "no workflow JSON files found in $WORKFLOWS_DIR"

# ── 2. Import workflows (stable id -> overwrite, never duplicate) ──────────
for f in "$RENDERED_DIR"/*.json; do
  name=$(basename "$f")
  log "importing $name"
  n8n import:workflow --input="$f"
done

# ── 3. Import credentials for enabled channels only ────────────────────────
CHANNELS=",${N8N_FIM_CHANNELS:-},"
CREDS_FILE="$RENDERED_DIR/credentials.json"
printf '[' > "$CREDS_FILE"
first_cred=1
add_cred() {
  # add_cred <json object, without surrounding brackets>
  if [ "$first_cred" = 1 ]; then
    first_cred=0
  else
    printf ',' >> "$CREDS_FILE"
  fi
  printf '%s' "$1" >> "$CREDS_FILE"
}

case "$CHANNELS" in
  *,email,*)
    log "channel enabled: email (credential: FIM Email SMTP)"
    add_cred "$(node -e '
      const d = {
        user: process.env.N8N_EMAIL_SMTP_USER || "",
        password: process.env.N8N_EMAIL_SMTP_PASSWORD || "",
        host: process.env.N8N_EMAIL_SMTP_HOST || "",
        port: Number(process.env.N8N_EMAIL_SMTP_PORT || 587),
        secure: (process.env.N8N_EMAIL_SMTP_SECURE || "false") === "true",
      };
      console.log(JSON.stringify({ id: "n8n-fim-email-smtp", name: "FIM Email SMTP", type: "smtp", data: d }));
    ')"
    ;;
esac

case "$CHANNELS" in
  *,slack,*)
    log "channel enabled: slack (credential: FIM Slack API)"
    add_cred "$(node -e '
      const d = { accessToken: process.env.N8N_SLACK_ACCESS_TOKEN || "" };
      console.log(JSON.stringify({ id: "n8n-fim-slack-api", name: "FIM Slack API", type: "slackApi", data: d }));
    ')"
    ;;
esac

case "$CHANNELS" in
  *,jira,*)
    log "channel enabled: jira (credential: FIM Jira API)"
    add_cred "$(node -e '
      const d = {
        email: process.env.N8N_JIRA_EMAIL || "",
        apiToken: process.env.N8N_JIRA_API_TOKEN || "",
        domain: process.env.N8N_JIRA_DOMAIN || "",
      };
      console.log(JSON.stringify({ id: "n8n-fim-jira-api", name: "FIM Jira API", type: "jiraSoftwareCloudApi", data: d }));
    ')"
    ;;
esac

case "$CHANNELS" in
  *,linear,*)
    log "channel enabled: linear (credential: FIM Linear API)"
    add_cred "$(node -e '
      const d = { name: "Authorization", value: process.env.N8N_LINEAR_API_KEY || "" };
      console.log(JSON.stringify({ id: "n8n-fim-linear-api", name: "FIM Linear API", type: "httpHeaderAuth", data: d }));
    ')"
    ;;
esac

printf ']' >> "$CREDS_FILE"

if [ "$first_cred" = 0 ]; then
  log "importing credentials for enabled channels"
  n8n import:credentials --input="$CREDS_FILE"
else
  log "N8N_FIM_CHANNELS is empty or names no recognized channel — no credentials imported"
fi

# ── 4. Publish every expected workflow ─────────────────────────────────────
for id in "$ROUTER_ID" "$EMAIL_ID" "$SLACK_ID" "$TICKET_ID"; do
  log "publishing workflow $id"
  n8n publish:workflow --id="$id"
done

# ── 5. Verify activation ────────────────────────────────────────────────────
ACTIVE_IDS=$(n8n list:workflow --active=true --onlyId)
for id in "$ROUTER_ID" "$EMAIL_ID" "$SLACK_ID" "$TICKET_ID"; do
  if ! printf '%s\n' "$ACTIVE_IDS" | grep -qx "$id"; then
    fail "workflow $id is not active after provisioning — n8n will not start"
  fi
done

log "all workflows imported, credentials provisioned, and activation verified"

# ── 6. Hand off to the real n8n process ─────────────────────────────────────
# Mirrors the "Trusting custom certificates" step of the image's own
# /docker-entrypoint.sh — a no-op here since nothing mounts
# /opt/custom-certificates, kept only so this entrypoint is a strict superset
# of the stock one rather than a silent behavior loss for a future user of
# that mount.
if [ -d /opt/custom-certificates ]; then
  echo "Trusting custom certificates from /opt/custom-certificates."
  export NODE_OPTIONS="--use-openssl-ca ${NODE_OPTIONS:-}"
  export SSL_CERT_DIR=/opt/custom-certificates
  c_rehash /opt/custom-certificates
fi

# `exec` replaces this shell's process image without running the EXIT trap
# above, so the temp dir is removed explicitly first — it would otherwise
# leak for the container's lifetime (harmless, but untidy).
rm -rf "$RENDERED_DIR"
trap - EXIT

log "starting n8n"
exec n8n "$@"
