#!/bin/sh
set -eu

WORKFLOW=/workflows/fim_alert_router.json
WORKFLOW_ID=5c01d9b8-702f-4de8-9672-7a515d62f10a

n8n import:workflow --input="$WORKFLOW"
n8n publish:workflow --id="$WORKFLOW_ID"

printf '%s\n' "Published workflow $WORKFLOW_ID at /webhook/fim-alert"
