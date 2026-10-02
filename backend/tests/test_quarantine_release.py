"""
Tests of `POST /events/{id}/quarantine/release` (Change 65, D83/RN-177).

Real Postgres (the conftest engine) and real authentication. Covers the
`backend-quarantine-release` requirements (endpoint, eligibility, concurrency,
audit, untouched event state) and the `backend-events-api` delta
(`quarantine_state` = `released` / `discarded`).
"""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from sqlmodel import Session, select

from app.core.database import engine
from app.core.security import create_access_token
from app.core.streams import verify_payload
from app.modules.actions.schemas import ReleaseMode
from app.modules.actions.service import (
    QuarantineNotReleasable,
    ReleaseInProgress,
    release_quarantine_single,
)
from app.modules.agents.models import Agent, AgentStatus
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import PublishedCommand, RulesetVersion

_SHA = "ab" * 32
_REASON = "falso positivo confirmado"


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent(session: Session, secret: bytes) -> Agent:
    a = Agent(
        agent_id=f"agent-rel-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


@pytest.fixture()
def admin_id(session: Session) -> int:
    return session.exec(select(User).where(User.role == "admin")).one().id


@pytest.fixture()
def operator_id(session: Session) -> int:
    user = User(
        username=f"operator-{uuid.uuid4().hex[:6]}",
        email=f"op-{uuid.uuid4().hex[:6]}@fim.local",
        password_hash="x",
        role="operator",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


def _headers(user_id: int, *, must_change_password: bool = False) -> dict[str, str]:
    token = create_access_token(
        user_id=user_id,
        username="whoever",
        must_change_password=must_change_password,
        jti=f"jti-rel-{uuid.uuid4().hex[:8]}",
    )
    return {"Authorization": f"Bearer {token}"}


def _event(
    session: Session,
    agent: Agent,
    status: EventStatus = EventStatus.quarantined,
    *,
    hash_detected: str = _SHA,
) -> Event:
    now = datetime.now(timezone.utc)
    ev = Event(
        event_id=str(uuid.uuid4()),
        agent_id=agent.agent_id,
        path=f"/etc/{uuid.uuid4().hex[:6]}",
        hash_detected=hash_detected,
        status=status,
        version=3,
        detected_at=now,
        received_at=now,
        created_at=now,
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
    error: str | None = None,
) -> PublishedCommand:
    body: dict[str, object] = {"type": command_type}
    if mode is not None:
        body["mode"] = mode
    cmd = PublishedCommand(
        command_type=command_type,
        target_agent_id=agent.agent_id,
        event_id=event.id,
        command_id=f"cmd-{uuid.uuid4().hex[:10]}",
        ack_status=ack_status,
        ruleset_version=0,
        status="published",
        published_at=datetime.now(timezone.utc),
        payload=json.dumps(body),
        error=error,
    )
    session.add(cmd)
    session.commit()
    return cmd


def _release_rows(session: Session, event: Event) -> list[PublishedCommand]:
    session.expire_all()
    return list(
        session.exec(
            select(PublishedCommand).where(
                PublishedCommand.event_id == event.id,
                PublishedCommand.command_type == "release_quarantine",
            )
        ).all()
    )


def _url(event: Event) -> str:
    return f"/events/{event.id}/quarantine/release"


# ── 6.1 endpoint, one test per mode ─────────────────────────────────────────


@pytest.mark.parametrize("mode", ["restore_original", "restore_baseline", "discard"])
async def test_release_is_accepted_and_enqueues_a_signed_command(
    client, session, agent, admin_id, secret, mode
) -> None:
    event = _event(session, agent)
    resp = await client.post(
        _url(event), json={"mode": mode, "reason": _REASON}, headers=_headers(admin_id)
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["event_id"] == event.id and body["mode"] == mode
    assert body["ack_status"] == "pending"

    (row,) = _release_rows(session, event)
    assert row.command_id == body["command_id"]
    assert row.ack_status == "pending" and row.target_agent_id == agent.agent_id
    payload = json.loads(row.payload)
    assert verify_payload(secret, payload)
    assert payload["type"] == "release_quarantine"
    assert payload["mode"] == mode
    assert payload["expected_sha256"] == _SHA
    assert payload["agent_event_id"] == event.event_id
    assert payload["event_id"] == event.id and payload["path"] == event.path
    assert payload["target_agent_id"] == agent.agent_id
    assert "reason" not in payload and _REASON not in row.payload
    if mode == "restore_original":
        assert isinstance(payload["ruleset_version"], int)
        assert row.ruleset_version == payload["ruleset_version"]
    else:
        assert "ruleset_version" not in payload
        assert row.ruleset_version == 0


async def test_restore_original_increments_ruleset_version_once(
    client, session, agent, admin_id
) -> None:
    event = _event(session, agent)
    before = session.exec(select(RulesetVersion)).first()
    before_version = before.version if before else 0
    resp = await client.post(
        _url(event), json={"mode": "restore_original", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 202

    session.expire_all()
    (row,) = _release_rows(session, event)
    assert row.ruleset_version == before_version + 1
    assert json.loads(row.payload)["ruleset_version"] == before_version + 1


@pytest.mark.parametrize("mode", ["restore_baseline", "discard"])
async def test_non_approving_modes_do_not_touch_ruleset_version(
    client, session, agent, admin_id, mode
) -> None:
    event = _event(session, agent)
    before = session.exec(select(RulesetVersion)).first()
    before_version = before.version if before else 0
    resp = await client.post(
        _url(event), json={"mode": mode, "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 202

    session.expire_all()
    after = session.exec(select(RulesetVersion)).first()
    assert (after.version if after else 0) == before_version


# ── 6.2 authorization ───────────────────────────────────────────────────────


async def test_requires_authentication(client, session, agent) -> None:
    event = _event(session, agent)
    resp = await client.post(_url(event), json={"mode": "discard", "reason": _REASON})
    assert resp.status_code == 401
    assert _release_rows(session, event) == []


async def test_rejects_non_admin(client, session, agent, operator_id) -> None:
    event = _event(session, agent)
    resp = await client.post(
        _url(event), json={"mode": "discard", "reason": _REASON}, headers=_headers(operator_id)
    )
    assert resp.status_code == 403
    assert _release_rows(session, event) == []


async def test_rejects_admin_who_must_change_password(client, session, agent, admin_id) -> None:
    event = _event(session, agent)
    resp = await client.post(
        _url(event),
        json={"mode": "discard", "reason": _REASON},
        headers=_headers(admin_id, must_change_password=True),
    )
    assert resp.status_code == 403
    assert _release_rows(session, event) == []


async def test_unknown_event_is_404(client, admin_id) -> None:
    resp = await client.post(
        "/events/999999/quarantine/release",
        json={"mode": "discard", "reason": _REASON},
        headers=_headers(admin_id),
    )
    assert resp.status_code == 404


# ── 6.3 validation ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "discard", "reason": ""},
        {"mode": "discard", "reason": "   \n  "},
        {"mode": "discard", "reason": "x" * 501},
        {"mode": "restore", "reason": _REASON},
        {"mode": "discard", "reason": _REASON, "extra": 1},
        {"reason": _REASON},
        {"mode": "discard"},
    ],
)
async def test_invalid_body_is_422_without_side_effects(
    client, session, agent, admin_id, body
) -> None:
    event = _event(session, agent)
    resp = await client.post(_url(event), json=body, headers=_headers(admin_id))

    assert resp.status_code == 422
    assert _release_rows(session, event) == []
    assert session.exec(select(AuditLog).where(AuditLog.action == "quarantine_release")).all() == []


async def test_reason_is_trimmed_and_limit_is_500(client, session, agent, admin_id) -> None:
    event = _event(session, agent)
    resp = await client.post(
        _url(event),
        json={"mode": "discard", "reason": "  " + "x" * 500 + "  "},
        headers=_headers(admin_id),
    )
    assert resp.status_code == 202
    session.expire_all()
    audit = session.exec(select(AuditLog).where(AuditLog.action == "quarantine_release")).one()
    assert json.loads(audit.detail)["reason"] == "x" * 500


# ── 6.4 eligibility ─────────────────────────────────────────────────────────


async def test_event_without_quarantine_is_not_releasable(client, session, agent, admin_id) -> None:
    event = _event(session, agent, EventStatus.approved)
    resp = await client.post(
        _url(event), json={"mode": "discard", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "quarantine_not_releasable"}
    assert _release_rows(session, event) == []


async def test_event_with_empty_hash_is_not_releasable(client, session, agent, admin_id) -> None:
    event = _event(session, agent, hash_detected="")
    resp = await client.post(
        _url(event), json={"mode": "discard", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "quarantine_not_releasable"}
    assert _release_rows(session, event) == []


async def test_confirmed_release_is_not_releasable_again(client, session, agent, admin_id) -> None:
    event = _event(session, agent)
    _command(session, agent, event, "release_quarantine", "acked", mode="restore_baseline")
    resp = await client.post(
        _url(event), json={"mode": "discard", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "quarantine_not_releasable"}


async def test_pending_release_is_in_progress(client, session, agent, admin_id) -> None:
    event = _event(session, agent)
    _command(session, agent, event, "release_quarantine", "pending", mode="discard")
    resp = await client.post(
        _url(event), json={"mode": "discard", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "release_in_progress"}
    assert len(_release_rows(session, event)) == 1


@pytest.mark.parametrize("ack_status,error", [("failed", "path_occupied"), ("timeout", None)])
async def test_previous_failed_or_timed_out_release_allows_a_retry(
    client, session, agent, admin_id, ack_status, error
) -> None:
    event = _event(session, agent)
    _command(session, agent, event, "release_quarantine", ack_status, mode="restore_original", error=error)
    resp = await client.post(
        _url(event), json={"mode": "restore_original", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 202
    assert len(_release_rows(session, event)) == 2


# ── 6.5 concurrency ─────────────────────────────────────────────────────────


def test_two_concurrent_requests_yield_one_command(session, agent, admin_id) -> None:
    event = _event(session, agent)

    def _attempt() -> str:
        with Session(engine) as s:
            try:
                return release_quarantine_single(
                    s, MagicMock(), event.id, ReleaseMode.discard, _REASON, admin_id
                )
            except ReleaseInProgress:
                return "release_in_progress"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _attempt(), range(2)))

    assert sorted(r == "release_in_progress" for r in results) == [False, True]
    assert len(_release_rows(session, event)) == 1


# ── 6.6 audit ───────────────────────────────────────────────────────────────


async def test_exactly_one_audit_entry_with_mode_reason_and_command_id(
    client, session, agent, admin_id
) -> None:
    event = _event(session, agent)
    resp = await client.post(
        _url(event), json={"mode": "restore_baseline", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 202

    session.expire_all()
    audit = session.exec(select(AuditLog).where(AuditLog.action == "quarantine_release")).all()
    assert len(audit) == 1
    entry = audit[0]
    assert (entry.user_id, entry.target_type, entry.target_id) == (admin_id, "event", event.id)
    assert json.loads(entry.detail) == {
        "mode": "restore_baseline",
        "reason": _REASON,
        "command_id": resp.json()["command_id"],
    }


def test_agent_without_secret_leaves_no_command_and_no_audit(session, admin_id) -> None:
    a = Agent(agent_id=f"agent-nosecret-{uuid.uuid4().hex[:6]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    event = _event(session, a)
    version_before = session.exec(select(RulesetVersion)).first()

    with Session(engine) as s:
        with pytest.raises(ValueError):
            release_quarantine_single(
                s, MagicMock(), event.id, ReleaseMode.restore_original, _REASON, admin_id
            )

    assert _release_rows(session, event) == []
    assert session.exec(select(AuditLog).where(AuditLog.action == "quarantine_release")).all() == []
    after = session.exec(select(RulesetVersion)).first()
    assert (after.version if after else 0) == (version_before.version if version_before else 0)


# ── 6.7 event state untouched ───────────────────────────────────────────────


@pytest.mark.parametrize("status", [EventStatus.quarantined, EventStatus.rejected])
async def test_event_state_is_not_modified(client, session, agent, admin_id, status) -> None:
    event = _event(session, agent, status)
    if status == EventStatus.rejected:
        _command(session, agent, event, "quarantine_file", "acked")
    resp = await client.post(
        _url(event), json={"mode": "discard", "reason": _REASON}, headers=_headers(admin_id)
    )
    assert resp.status_code == 202

    session.expire_all()
    persisted = session.get(Event, event.id)
    assert persisted.status == status
    assert persisted.version == 3
    assert persisted.resolved_at is None and persisted.resolved_by is None


# ── 6.9 quarantine_state derivation ─────────────────────────────────────────


async def _state(client, event: Event, admin_id: int) -> str:
    resp = await client.get(f"/events/{event.id}", headers=_headers(admin_id))
    assert resp.status_code == 200
    return resp.json()["quarantine_state"]


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("restore_original", "released"),
        ("restore_baseline", "released"),
        ("discard", "discarded"),
    ],
)
async def test_acked_release_derives_released_or_discarded(
    client, session, agent, admin_id, mode, expected
) -> None:
    event = _event(session, agent)
    assert await _state(client, event, admin_id) == "quarantined"
    _command(session, agent, event, "release_quarantine", "acked", mode=mode)

    assert await _state(client, event, admin_id) == expected
    session.expire_all()
    assert session.get(Event, event.id).status == EventStatus.quarantined


@pytest.mark.parametrize("ack_status", ["pending", "failed", "timeout"])
async def test_unconfirmed_release_keeps_the_quarantine(
    client, session, agent, admin_id, ack_status
) -> None:
    event = _event(session, agent)
    _command(session, agent, event, "release_quarantine", ack_status, mode="discard")
    assert await _state(client, event, admin_id) == "quarantined"


async def test_released_state_is_filterable(client, session, agent, admin_id) -> None:
    released = _event(session, agent)
    discarded = _event(session, agent)
    still = _event(session, agent)
    _command(session, agent, released, "release_quarantine", "acked", mode="restore_baseline")
    _command(session, agent, discarded, "release_quarantine", "acked", mode="discard")

    async def _ids(state: str) -> set[int]:
        resp = await client.get(
            f"/events?quarantine_state={state}&include_superseded=true", headers=_headers(admin_id)
        )
        assert resp.status_code == 200
        return {i["id"] for i in resp.json()["items"]}

    assert await _ids("released") == {released.id}
    assert await _ids("discarded") == {discarded.id}
    assert await _ids("quarantined") == {still.id}
