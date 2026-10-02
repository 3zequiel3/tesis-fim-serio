"""
Tests of the `command_ack` handling of `release_quarantine` (Change 65, D83/RN-177).

Only `restore_original` approves the quarantined content, so only its `ok` ack
reconciles `baseline_entries` and advances `ruleset_version_applied`. The mode is
read from the payload persisted in the row, never from the ack. In-memory SQLite,
same harness as `test_command_ack_consumer.py`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.streams import sign_payload
from app.modules.agents.models import Agent, AgentStatus, BaselineEntry, BaselineStatus
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import PublishedCommand

_SHA = "cd" * 32


@pytest.fixture()
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, secret) -> Agent:
    a = Agent(
        agent_id="agent-rel-ack",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
        ruleset_version_applied=5,
    )
    with Session(mem_engine) as s:
        s.add(a)
        s.commit()
        s.refresh(a)
    return a


@pytest.fixture()
def event(mem_engine, agent) -> Event:
    now = datetime.now(timezone.utc)
    ev = Event(
        event_id="evt-rel-ack",
        agent_id=agent.agent_id,
        path="/etc/rel-ack",
        hash_detected=_SHA,
        status=EventStatus.quarantined,
        detected_at=now,
        received_at=now,
    )
    with Session(mem_engine) as s:
        s.add(ev)
        s.commit()
        s.refresh(ev)
    return ev


def _release_command(mem_engine, agent, event, mode: str, *, command_id: str, version: int = 9):
    cmd = PublishedCommand(
        command_type="release_quarantine",
        target_agent_id=agent.agent_id,
        event_id=event.id,
        command_id=command_id,
        ack_status="pending",
        ruleset_version=version if mode == "restore_original" else 0,
        status="published",
        published_at=datetime.now(timezone.utc),
        payload=json.dumps({"type": "release_quarantine", "mode": mode}),
    )
    with Session(mem_engine) as s:
        s.add(cmd)
        s.commit()
    return cmd


def _ack(mem_engine, agent, secret, command_id: str, *, ok: bool, error: str | None = None, **extra):
    import app.modules.agents.command_ack_consumer as mod

    payload: dict = {
        "command_id": command_id,
        "command_type": "release_quarantine",
        "event_id": 1,
        "agent_id": agent.agent_id,
        "status": "ok" if ok else "error",
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    payload["signature"] = sign_payload(secret, payload)
    with patch.object(mod, "engine", mem_engine):
        mod._handle_command_ack({"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))})


def _baseline(mem_engine, agent, event):
    with Session(mem_engine) as s:
        return s.exec(
            select(BaselineEntry).where(
                BaselineEntry.path == event.path, BaselineEntry.agent_id == agent.agent_id
            )
        ).first()


def _row(mem_engine, command_id: str) -> PublishedCommand:
    with Session(mem_engine) as s:
        return s.exec(select(PublishedCommand).where(PublishedCommand.command_id == command_id)).one()


def _applied(mem_engine, agent) -> int:
    with Session(mem_engine) as s:
        return s.exec(select(Agent).where(Agent.agent_id == agent.agent_id)).one().ruleset_version_applied


def test_ok_restore_original_reconciles_baseline_and_advances_version(
    mem_engine, agent, event, secret
) -> None:
    _release_command(mem_engine, agent, event, "restore_original", command_id="cmd-ro")
    _ack(mem_engine, agent, secret, "cmd-ro", ok=True)

    assert _row(mem_engine, "cmd-ro").ack_status == "acked"
    entry = _baseline(mem_engine, agent, event)
    assert entry is not None
    assert (entry.hash, entry.status, entry.ruleset_version) == (_SHA, BaselineStatus.present, 9)
    assert _applied(mem_engine, agent) == 9


@pytest.mark.parametrize("mode", ["restore_baseline", "discard"])
def test_ok_other_modes_do_not_touch_baseline_entries(mem_engine, agent, event, secret, mode) -> None:
    _release_command(mem_engine, agent, event, mode, command_id=f"cmd-{mode}")
    _ack(mem_engine, agent, secret, f"cmd-{mode}", ok=True)

    assert _row(mem_engine, f"cmd-{mode}").ack_status == "acked"
    assert _baseline(mem_engine, agent, event) is None
    assert _applied(mem_engine, agent) == 5


def test_error_ack_fails_the_row_without_reconciling(mem_engine, agent, event, secret) -> None:
    _release_command(mem_engine, agent, event, "restore_original", command_id="cmd-err")
    _ack(mem_engine, agent, secret, "cmd-err", ok=False, error="path_occupied")

    row = _row(mem_engine, "cmd-err")
    assert (row.ack_status, row.error) == ("failed", "path_occupied")
    assert _baseline(mem_engine, agent, event) is None
    assert _applied(mem_engine, agent) == 5


def test_mode_comes_from_the_persisted_payload_not_from_the_ack(
    mem_engine, agent, event, secret
) -> None:
    _release_command(mem_engine, agent, event, "discard", command_id="cmd-spoof")
    _ack(mem_engine, agent, secret, "cmd-spoof", ok=True, mode="restore_original", ruleset_version=99)

    assert _baseline(mem_engine, agent, event) is None
    assert _applied(mem_engine, agent) == 5


def test_a_repeated_ack_does_not_reapply_effects(mem_engine, agent, event, secret) -> None:
    _release_command(mem_engine, agent, event, "restore_original", command_id="cmd-twice")
    _ack(mem_engine, agent, secret, "cmd-twice", ok=True)
    with Session(mem_engine) as s:
        a = s.exec(select(Agent).where(Agent.agent_id == agent.agent_id)).one()
        a.ruleset_version_applied = 20
        s.add(a)
        s.commit()
    _ack(mem_engine, agent, secret, "cmd-twice", ok=True)

    assert _applied(mem_engine, agent) == 20


def test_unacknowledged_release_times_out_in_the_sweep(mem_engine, agent, event) -> None:
    import app.modules.agents.command_ack_consumer as mod

    cmd = _release_command(mem_engine, agent, event, "discard", command_id="cmd-timeout")
    with Session(mem_engine) as s:
        row = s.exec(select(PublishedCommand).where(PublishedCommand.command_id == "cmd-timeout")).one()
        row.published_at = datetime.now(timezone.utc) - timedelta(days=1)
        s.add(row)
        s.commit()
    with patch.object(mod, "engine", mem_engine):
        mod._sweep_timeouts()

    assert _row(mem_engine, "cmd-timeout").ack_status == "timeout"
