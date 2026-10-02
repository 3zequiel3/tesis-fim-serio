"""
Change 62 (D80/RN-174) — `detected_offline` on Event: tolerant ingestion, additive
output and an additive migration 023.

Same pattern as test_event_action_error.py: SQLite in-memory for `ingest_event`,
plain model validation for `EventOut`, text inspection for the migration.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from sqlmodel import SQLModel, create_engine

import app.modules.events.service as svc
from app.modules.events.models import Event, EventStatus
from app.modules.events.router import EventDetailOut, _to_event_detail_out, _to_event_out
from app.modules.events.service import ingest_event


@pytest.fixture()
def mem_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload(event_id: str, **extra) -> dict:
    return {
        "event_id": event_id,
        "agent_id": "agent-test",
        "path": "/etc/hosts",
        "hash_detected": "deadbeef",
        "action": "alert_only",
        **extra,
    }


def _ingest(mem_engine, payload: dict) -> Event:
    now = _now()
    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)
    assert event is not None
    return event


def test_ingest_persists_true(mem_engine) -> None:
    assert _ingest(mem_engine, _payload("off-1", detected_offline=True)).detected_offline is True


def test_ingest_persists_false(mem_engine) -> None:
    assert _ingest(mem_engine, _payload("off-2", detected_offline=False)).detected_offline is False


def test_ingest_missing_key_is_null(mem_engine) -> None:
    assert _ingest(mem_engine, _payload("off-3")).detected_offline is None


@pytest.mark.parametrize("bad", ["yes", 1, 0, "true", ["x"]])
def test_ingest_non_boolean_is_null_and_logged(mem_engine, bad) -> None:
    with patch.object(svc, "log") as log:
        event = _ingest(mem_engine, _payload("off-4", detected_offline=bad))

    assert event.detected_offline is None
    log.warning.assert_any_call(
        "consumer.detected_offline_invalid",
        event_id="off-4",
        value_type=type(bad).__name__,
    )


def test_detected_offline_does_not_change_status(mem_engine) -> None:
    a = _ingest(mem_engine, _payload("off-5", detected_offline=True))
    b = _ingest(mem_engine, _payload("off-6", detected_offline=False))
    c = _ingest(mem_engine, _payload("off-7", action="auto_restore", detected_offline=True))

    assert a.status == b.status == EventStatus.alert_only
    assert c.status == EventStatus.auto_restored
    assert a.severity == b.severity


@pytest.mark.parametrize("value", [True, False, None])
def test_event_out_and_detail_expose_value_including_null(mem_engine, value) -> None:
    extra = {} if value is None else {"detected_offline": value}
    event = _ingest(mem_engine, _payload(f"off-out-{value}", **extra))

    out = _to_event_out(event, {})
    detail = _to_event_detail_out(event, {})

    assert out.detected_offline is value
    assert isinstance(detail, EventDetailOut)
    assert detail.detected_offline is value
    assert "detected_offline" in out.model_dump()


def test_migration_023_is_a_single_additive_statement() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "db"
        / "migrations"
        / "023_add_event_detected_offline.sql"
    )
    sql = path.read_text()
    code = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    statements = [s.strip() for s in code.split(";") if s.strip()]

    assert statements == ["ALTER TABLE events ADD COLUMN IF NOT EXISTS detected_offline BOOLEAN"]
    assert not re.search(r"\b(DEFAULT|UPDATE|CREATE\s+INDEX|NOT\s+NULL)\b", code, re.IGNORECASE)
