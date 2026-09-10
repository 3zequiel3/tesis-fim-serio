"""Focused regressions for the first backend drain optimization unit."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import event as sa_event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.core.streams import SCHEMA_VERSION, sign_payload, verify_payload
from app.modules.agents.models import Agent, AgentStatus
from app.modules.alerts.models import Alert, AlertSeverity
from app.modules.events.models import Event, EventStatus
from app.modules.events.service import IngestDisposition, _ingest_event_outcome
from app.modules.rules.models import RuleSeverity


def _engine():
    db = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(db)
    return db


def _seed_agent(db, secret: bytes, status: AgentStatus = AgentStatus.online) -> None:
    with Session(db) as session:
        session.add(Agent(agent_id="agent-drain", status=status, shared_secret_hex=secret.hex()))
        session.commit()


def _payload(secret: bytes, *, event_id: str | None = None, path: str = "/etc/passwd") -> dict:
    value = {
        "event_id": event_id or str(uuid.uuid4()),
        "agent_id": "agent-drain",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": path,
        "hash_detected": "detected",
    }
    value["signature"] = sign_payload(secret, value)
    return value


class _AtomicPipeline:
    def __init__(self, client: "_AtomicClient") -> None:
        self.client = client
        self.pending: list[tuple[str, tuple]] = []

    def xadd(self, *args):
        self.pending.append(("xadd", args))
        return self

    def xack(self, *args):
        self.pending.append(("xack", args))
        return self

    async def execute(self):
        self.client.execute_calls += 1
        if self.client.fail_execute:
            raise RuntimeError("valkey unavailable")
        self.client.effects.extend(self.pending)
        return ["1-0", 1]


class _AtomicClient:
    def __init__(self, *, fail_execute: bool = False) -> None:
        self.fail_execute = fail_execute
        self.execute_calls = 0
        self.effects: list[tuple[str, tuple]] = []

    def pipeline(self, *, transaction: bool):
        assert transaction is True
        return _AtomicPipeline(self)


async def _handle(db, client, payload: dict) -> None:
    import app.modules.events.consumer as consumer
    import app.modules.events.service as service

    with (
        patch.object(consumer, "engine", db),
        patch.object(service, "engine", db),
        patch.object(consumer, "_fire_and_forget"),
    ):
        await consumer._handle_message(
            client,
            "1-0",
            {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))},
        )


def test_agent_credentials_and_revocation_use_one_select() -> None:
    import app.modules.events.consumer as consumer

    db = _engine()
    secret = os.urandom(32)
    _seed_agent(db, secret, AgentStatus.revoked)
    selects = 0

    def count(_conn, _cursor, statement, _params, _context, _many):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    sa_event.listen(db, "before_cursor_execute", count)
    with patch.object(consumer, "engine", db):
        auth = consumer._get_agent_auth("agent-drain")

    assert auth.shared_secret == secret
    assert auth.revoked is True
    assert selects == 1


def test_revoked_agent_is_acknowledged_without_ingestion_or_response() -> None:
    db = _engine()
    secret = os.urandom(32)
    _seed_agent(db, secret, AgentStatus.revoked)
    payload = _payload(secret)
    client = AsyncMock()
    client.xack = AsyncMock()
    client.xadd = AsyncMock()

    asyncio.run(_handle(db, client, payload))

    client.xack.assert_awaited_once()
    client.xadd.assert_not_awaited()
    with Session(db) as session:
        assert session.exec(select(Event)).all() == []


def test_duplicate_is_decided_before_rate_limit_and_supersession() -> None:
    import app.modules.events.service as service

    db = _engine()
    secret = os.urandom(32)
    _seed_agent(db, secret)
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with Session(db) as session:
        session.add(Event(
            event_id=event_id,
            agent_id="agent-drain",
            path="/etc/passwd",
            hash_detected="first",
            status=EventStatus.pending,
            detected_at=now,
            received_at=now,
        ))
        session.commit()

    reserved = False

    def reserve() -> bool:
        nonlocal reserved
        reserved = True
        return True

    with patch.object(service, "engine", db), patch.object(service, "mark_superseded") as supersede:
        outcome = _ingest_event_outcome(
            _payload(secret, event_id=event_id), now, now,
            accept_new=reserve,
        )

    assert outcome.disposition == IngestDisposition.duplicate
    assert reserved is False
    supersede.assert_not_called()
    with Session(db) as session:
        assert len(session.exec(select(Event)).all()) == 1


def test_commit_then_valkey_failure_leaves_message_for_safe_redelivery() -> None:
    db = _engine()
    secret = os.urandom(32)
    _seed_agent(db, secret)
    payload = _payload(secret)
    failing = _AtomicClient(fail_execute=True)

    try:
        asyncio.run(_handle(db, failing, payload))
    except RuntimeError as exc:
        assert str(exc) == "valkey unavailable"
    else:
        raise AssertionError("Valkey failure must propagate to preserve the PEL entry")

    assert failing.effects == []  # transaction applied neither XADD nor XACK
    with Session(db) as session:
        assert len(session.exec(select(Event)).all()) == 1  # DB commit already durable

    recovered = _AtomicClient()
    asyncio.run(_handle(db, recovered, payload))
    assert [name for name, _args in recovered.effects] == ["xadd", "xack"]
    with Session(db) as session:
        assert len(session.exec(select(Event)).all()) == 1

    ack = json.loads(recovered.effects[0][1][1]["data"])
    assert ack["type"] == "event_ack"
    assert ack["event_id"] == payload["event_id"]
    assert verify_payload(secret, ack)


def test_notification_reuses_persisted_severity_snapshot() -> None:
    import app.modules.alerts.service as alerts

    db = _engine()
    secret = os.urandom(32)
    _seed_agent(db, secret)
    now = datetime.now(timezone.utc)
    with Session(db) as session:
        stored = Event(
            event_id=str(uuid.uuid4()),
            agent_id="agent-drain",
            path="/etc/passwd",
            hash_detected="hash",
            status=EventStatus.pending,
            severity=RuleSeverity.high,
            detected_at=now,
            received_at=now,
        )
        session.add(stored)
        session.commit()
        session.refresh(stored)
        session.expunge(stored)

    with (
        patch.object(alerts, "engine", db),
        patch.object(alerts, "_determine_severity", side_effect=AssertionError("must not re-query rules")),
        patch.object(alerts, "notify_event", new=AsyncMock()),
    ):
        asyncio.run(alerts.notify_if_applicable(stored))

    with Session(db) as session:
        rows = session.exec(select(Alert)).all()
    assert len(rows) == 1
    assert rows[0].severity == AlertSeverity.high


def test_new_low_severity_event_uses_five_sql_statements_before_dispatch() -> None:
    import app.modules.events.consumer as consumer
    import app.modules.events.service as service

    db = _engine()
    secret = os.urandom(32)
    _seed_agent(db, secret)
    payload = _payload(secret)
    now = datetime.now(timezone.utc)
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    sa_event.listen(db, "before_cursor_execute", count)
    with patch.object(consumer, "engine", db), patch.object(service, "engine", db):
        auth = consumer._get_agent_auth("agent-drain")
        assert auth.shared_secret == secret
        outcome = _ingest_event_outcome(
            payload, now, now, accept_new=lambda: True,
        )

    assert outcome.disposition == IngestDisposition.persisted
    assert statements.count("SELECT") == 4  # auth, dedup, pending, rules
    assert statements.count("INSERT") == 1
    assert len(statements) == 5
