#!/usr/bin/env python3
"""Send one synthetic alert through the real backend n8n transport."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

from app.modules.alerts.notifier import send_n8n


async def main() -> int:
    url = os.environ.get("N8N_WEBHOOK_URL", "http://127.0.0.1:15678/webhook/fim-alert")
    now = datetime.now(timezone.utc).isoformat()
    notification_id = f"controlled-{uuid4()}"
    payload = {
        "schema_version": 1,
        "notification_id": notification_id,
        "type": "alert",
        "alert_id": 1,
        "event_id": str(uuid4()),
        "path": "/tmp/fim-controlled-e2e.txt",
        "severity": "high",
        "status": "alert_only",
        "action_taken": "alert_only",
        "action_failed": False,
        "is_symlink": False,
        "agent_id": "controlled-agent",
        "process_pid": 1234,
        "process_uid": 1000,
        "process_exe": "/usr/bin/touch",
        "detected_at": now,
        "received_at": now,
        "alert_created_at": now,
    }
    delivered = await send_n8n(payload, url)
    print(f"notification_id={notification_id} delivered={str(delivered).lower()}")
    return 0 if delivered else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
