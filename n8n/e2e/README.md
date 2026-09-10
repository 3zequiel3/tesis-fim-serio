# Controlled n8n end-to-end harness

This harness proves the bounded path `backend notifier -> n8n -> controlled
receiver` without commercial providers or real recipients. It does not replace
the production compose file and stores only synthetic test records.

## Run

```bash
export N8N_ENCRYPTION_KEY="$(openssl rand -hex 32)"
docker compose -f n8n/docker-compose.e2e.yml up -d --wait
PYTHONPATH=backend backend/.venv/bin/python n8n/e2e/send-test-alert.py
curl -fsS http://127.0.0.1:18081/receipts | python -m json.tool
docker compose -f n8n/docker-compose.e2e.yml down -v
```

The workflow setup container imports the fixed workflow ID and publishes it
before n8n starts. Re-running the setup therefore updates the same workflow
rather than creating a second router.

The receiver commits each unique `notification_id` to SQLite before returning
HTTP 202. The workflow uses `responseMode=responseNode`: n8n acknowledges the
backend only after the controlled receiver returns success. A receiver error or
outage prevents a false n8n success.

Each record separates these clocks:

- `received_at`: backend event reception;
- `backend_dispatched_at`: immediately before the backend HTTP request;
- `n8n_accepted_at`: workflow acceptance;
- `receiver_received_at`: durable controlled-receiver receipt.

Set `RECEIVER_STATUS_CODE=503` before starting the stack to exercise receiver
failure. Stop the `n8n` service to exercise orchestrator unavailability. The
backend fallback cascade and durable alert retry state remain a separate work
unit; this harness does not claim those paths as end-to-end validated.

The raw summary of the new controlled run is stored in
`evidence/20260909-run.json`. It includes the initially detected false-success
defect and clearly excludes the durable fallback work unit.
