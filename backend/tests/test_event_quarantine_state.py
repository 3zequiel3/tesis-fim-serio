"""
Tests of `quarantine_state` (D82/RN-176, Change 64): derived on every read,
filterable in SQL, never a column and never an event state.

Covers the seven scenarios of the `backend-events-api` requirement plus the
robustness cases of the expression (a non-`release_quarantine` row with an empty
payload must not break the JSONB cast). Real Postgres and real authentication,
same harness as `test_event_listing_contract.py`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from sqlmodel import Session

from app.core.database import engine
from app.core.security import create_access_token
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus, QuarantineState
from app.modules.rules.models import PublishedCommand

_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(agent_id=f"agent-qstate-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _auth_headers() -> dict[str, str]:
    token = create_access_token(
        user_id=1, username="admin", must_change_password=False, jti="test-jti-qstate"
    )
    return {"Authorization": f"Bearer {token}"}


def _event(session: Session, agent: Agent, status: EventStatus) -> Event:
    ev = Event(
        event_id=f"evt-qstate-{uuid.uuid4().hex[:12]}",
        agent_id=agent.agent_id,
        path=f"/etc/{uuid.uuid4().hex[:6]}",
        hash_detected="deadbeef",
        status=status,
        detected_at=_NOW,
        received_at=_NOW,
        created_at=_NOW,
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def _command(
    session: Session,
    agent: Agent,
    event: Event,
    command_type: str,
    ack_status: str | None,
    *,
    mode: str | None = None,
    payload: str | None = None,
) -> PublishedCommand:
    if payload is None:
        body: dict[str, object] = {"type": command_type}
        if mode is not None:
            body["mode"] = mode
        payload = json.dumps(body)
    cmd = PublishedCommand(
        command_type=command_type,
        target_agent_id=agent.agent_id,
        event_id=event.id,
        command_id=f"cmd-qstate-{uuid.uuid4().hex[:10]}",
        ack_status=ack_status,
        ruleset_version=0,
        status="published",
        published_at=_NOW,
        payload=payload,
    )
    session.add(cmd)
    session.commit()
    return cmd


async def _state_of(client, event: Event) -> str:
    resp = await client.get("/events?include_superseded=true", headers=_auth_headers())
    assert resp.status_code == 200
    return {i["id"]: i["quarantine_state"] for i in resp.json()["items"]}[event.id]


async def test_automatic_quarantine_is_quarantined(client, session, agent) -> None:
    ev = _event(session, agent, EventStatus.quarantined)

    assert await _state_of(client, ev) == "quarantined"


async def test_rejected_with_acked_quarantine_file_is_quarantined_and_stays_rejected(
    client, session, agent
) -> None:
    ev = _event(session, agent, EventStatus.rejected)
    _command(session, agent, ev, "quarantine_file", "acked")

    resp = await client.get("/events", headers=_auth_headers())
    item = next(i for i in resp.json()["items"] if i["id"] == ev.id)

    assert item["quarantine_state"] == "quarantined"
    assert item["status"] == "rejected"
    session.expire_all()
    assert session.get(Event, ev.id).status == EventStatus.rejected  # RN-72 untouched


@pytest.mark.parametrize("ack_status", ["pending", "failed", "timeout"])
async def test_rejected_with_unconfirmed_quarantine_file_is_none(
    client, session, agent, ack_status: str
) -> None:
    ev = _event(session, agent, EventStatus.rejected)
    _command(session, agent, ev, "quarantine_file", ack_status)

    assert await _state_of(client, ev) == "none"


async def test_rejected_with_restore_file_is_none(client, session, agent) -> None:
    ev = _event(session, agent, EventStatus.rejected)
    _command(session, agent, ev, "restore_file", "acked")

    assert await _state_of(client, ev) == "none"


async def test_discarded_and_released_are_read_from_the_release_command(
    client, session, agent
) -> None:
    discarded = _event(session, agent, EventStatus.rejected)
    _command(session, agent, discarded, "quarantine_file", "acked")
    _command(session, agent, discarded, "release_quarantine", "acked", mode="discard")
    released_orig = _event(session, agent, EventStatus.quarantined)
    _command(session, agent, released_orig, "release_quarantine", "acked", mode="restore_original")
    released_base = _event(session, agent, EventStatus.rejected)
    _command(session, agent, released_base, "quarantine_file", "acked")
    _command(session, agent, released_base, "release_quarantine", "acked", mode="restore_baseline")
    pending_release = _event(session, agent, EventStatus.quarantined)
    _command(session, agent, pending_release, "release_quarantine", "pending", mode="discard")

    assert await _state_of(client, discarded) == "discarded"
    assert await _state_of(client, released_orig) == "released"
    assert await _state_of(client, released_base) == "released"
    assert await _state_of(client, pending_release) == "quarantined"


async def test_release_without_quarantine_base_stays_none(client, session, agent) -> None:
    ev = _event(session, agent, EventStatus.pending)
    _command(session, agent, ev, "release_quarantine", "acked", mode="discard")

    assert await _state_of(client, ev) == "none"


async def test_filter_resolves_in_sql_with_correct_total_and_pagination(
    client, session, agent
) -> None:
    auto = _event(session, agent, EventStatus.quarantined)
    rejected_q = _event(session, agent, EventStatus.rejected)
    _command(session, agent, rejected_q, "quarantine_file", "acked")
    rejected_r = _event(session, agent, EventStatus.rejected)
    _command(session, agent, rejected_r, "restore_file", "acked")
    _event(session, agent, EventStatus.pending)

    resp = await client.get("/events?quarantine_state=quarantined", headers=_auth_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {i["id"] for i in body["items"]} == {auto.id, rejected_q.id}

    paged = await client.get(
        "/events?quarantine_state=quarantined&page_size=1&page=2", headers=_auth_headers()
    )
    assert paged.json()["total"] == 2
    assert len(paged.json()["items"]) == 1

    repeated = await client.get(
        "/events?quarantine_state=quarantined&quarantine_state=none", headers=_auth_headers()
    )
    assert repeated.json()["total"] == 4

    combined = await client.get(
        "/events?quarantine_state=quarantined&status=rejected", headers=_auth_headers()
    )
    assert [i["id"] for i in combined.json()["items"]] == [rejected_q.id]


async def test_unknown_filter_value_is_422(client) -> None:
    resp = await client.get("/events?quarantine_state=foo", headers=_auth_headers())

    assert resp.status_code == 422


async def test_other_command_type_with_empty_payload_does_not_break_the_expression(
    client, session, agent
) -> None:
    ev = _event(session, agent, EventStatus.rejected)
    _command(session, agent, ev, "restore_file", "acked", payload="")
    _command(session, agent, ev, "quarantine_file", "acked", payload="")

    resp = await client.get("/events?quarantine_state=quarantined", headers=_auth_headers())

    assert resp.status_code == 200
    assert [i["id"] for i in resp.json()["items"]] == [ev.id]


async def test_detail_and_chain_expose_the_same_state(client, session, agent) -> None:
    ev = _event(session, agent, EventStatus.rejected)
    _command(session, agent, ev, "quarantine_file", "acked")

    detail = await client.get(f"/events/{ev.id}", headers=_auth_headers())
    chain = await client.get(f"/events/{ev.id}/chain", headers=_auth_headers())

    assert detail.status_code == 200 and chain.status_code == 200
    assert detail.json()["quarantine_state"] == "quarantined"
    assert chain.json()["items"][0]["quarantine_state"] == "quarantined"


def test_quarantine_state_is_never_a_persisted_event_column() -> None:
    assert "quarantine_state" not in Event.__table__.columns  # type: ignore[attr-defined]
    assert {s.value for s in QuarantineState} == {"none", "quarantined", "released", "discarded"}
