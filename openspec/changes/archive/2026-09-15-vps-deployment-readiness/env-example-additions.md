# `.env.example` additions pending manual application

This session's sandbox denies all read/write access to `.env.example` by
permission rule (unrelated to this change's own scope — see task 7.4's
finding and design.md's D-6 addendum "Risks" entry). `.env.example` itself
already carries the D53–D56 variables from groups 2–5 (task 4.1, done in a
previous batch); what remains pending is the n8n per-channel provisioning
set from group 6 (D58/RN-152), referenced by `n8n/provision/provision.sh`
and `n8n/provision/render.js`.

Whoever next has write access to `.env.example` should append the block
below, in a section near the existing n8n variables
(`N8N_ENCRYPTION_KEY`, `N8N_INSTANCE_OWNER_*`). Nothing here needs a
value checked into version control — every line is a name/comment/default
only, exactly as `.env.example` documents every other secret.

```sh
# ── n8n alert routing channels (D58/RN-152) ──────────────────────────────────
# Comma-separated list of channels the productive router (n8n/workflows/
# fim_alert_router.json) enables. Recognized tokens: email, slack, jira,
# linear. A channel left out responds channel_disabled (D43/RN-137: an
# unconfigured channel is not reported healthy). Example: email,slack
N8N_FIM_CHANNELS=

# Email channel (SMTP)
N8N_EMAIL_FROM=
N8N_EMAIL_TO=
N8N_EMAIL_SMTP_HOST=
N8N_EMAIL_SMTP_PORT=587
N8N_EMAIL_SMTP_USER=
N8N_EMAIL_SMTP_PASSWORD=
N8N_EMAIL_SMTP_SECURE=false

# Slack channel — uses the Web API (chat.postMessage) via a bot token, not an
# incoming webhook URL: n8n has no credential type for a raw webhook URL, and
# RN-52 requires the node to declare `credentials`, never an embedded secret.
N8N_SLACK_ACCESS_TOKEN=
N8N_SLACK_CHANNEL=
# Only override to point at a controlled receiver in tests.
N8N_SLACK_API_URL=https://slack.com/api/chat.postMessage

# Ticketing — Jira and Linear are two independent channels inside the single
# ticketing sub-flow (n8n/workflows/ticketing_alert.json); both may be
# enabled at once, each with its own search-before-create (D41/RN-135).
# `ticketing_system` in the payload is prohibited (RN-52) — enablement lives
# here, not in the event.
N8N_TICKETING_JIRA_ENABLED=false
N8N_JIRA_EMAIL=
N8N_JIRA_API_TOKEN=
N8N_JIRA_DOMAIN=
N8N_JIRA_PROJECT_KEY=

N8N_TICKETING_LINEAR_ENABLED=false
N8N_LINEAR_API_KEY=
N8N_LINEAR_API_URL=https://api.linear.app/graphql
N8N_LINEAR_TEAM_ID=
```

Once applied, delete this file (or leave it — `openspec archive` does not
require it to be removed, but it stops being accurate the moment
`.env.example` has these lines).

See also:
- `docs/despliegue_servidor_remoto.md` §"Preparación del `.env`" — documents
  these variables for the operator, independent of whether `.env.example`
  already lists them.
- `openspec/changes/vps-deployment-readiness/design.md` §D-6 addendum — the
  authoritative definition of each variable's semantics and defaults.
- `openspec/changes/vps-deployment-readiness/tasks.md` task 7.4 — where the
  sandbox restriction was first hit.
