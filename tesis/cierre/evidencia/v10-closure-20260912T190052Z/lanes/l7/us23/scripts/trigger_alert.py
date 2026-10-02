"""Run inside the lab backend container (via `docker compose exec -T backend
python3 - < trigger_alert.py`) to drive the real notification cascade
(app.modules.alerts.service.notify_if_applicable / notify_event) against a
freshly persisted Event row, without needing a full agent fanotify round trip
for every fallback scenario (the real fanotify path is covered by the US-24
lab). Reads AGENT_ID, EVENT_PATH, SEVERITY from the environment.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

from sqlmodel import Session

from app.core.database import engine
from app.modules.alerts.service import notify_if_applicable
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RuleSeverity


async def main() -> None:
    now = datetime.now(timezone.utc)
    event = Event(
        event_id=str(uuid.uuid4()),
        agent_id=os.environ["AGENT_ID"],
        path=os.environ["EVENT_PATH"],
        hash_detected="a" * 64,
        status=EventStatus.pending,
        severity=RuleSeverity(os.environ.get("SEVERITY", "critical")),
        detected_at=now,
        received_at=now,
        process_pid=4242,
        process_uid=0,
        process_exe="/usr/bin/vim",
    )
    with Session(engine) as session:
        session.add(event)
        session.commit()
        session.refresh(event)
        print(f"event_id={event.event_id} db_id={event.id}")

    await notify_if_applicable(event)


asyncio.run(main())
