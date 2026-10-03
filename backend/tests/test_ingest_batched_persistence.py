"""
Phase B of `ingest-batched-persistence` (amplification of 2026-10-03 of D87/RN-181):
service-level tests of the ingest core shared by the per-event path and the batch
(`_ingest_batch`), against the in-memory test engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.modules.events.service as service_mod
from app.modules.audit.models import AuditLog  # noqa: F401  (table for compact_chain)
from app.modules.events.models import Event, EventStatus
from app.modules.events.service import (
    IngestBatchItem,
    IngestDisposition,
    InvalidTransitionError,
    _ingest_batch,
    _ingest_event_outcome,
)
from app.modules.rules.models import Rule, RuleAction, RuleSeverity
from app.modules.rules.service import determine_severity_for_path, severity_from_rules


@pytest.fixture()
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with patch.object(service_mod, "engine", engine):
        yield engine


def _item(path: str | None = "/etc/x", action: str = "manual_review", agent: str = "a1", event_id: str | None = None):
    now = datetime.now(timezone.utc)
    data = {
        "event_id": event_id or str(uuid.uuid4()),
        "agent_id": agent,
        "path": path,
        "hash_detected": "abc",
        "action": action,
    }
    return IngestBatchItem(data, now, now, agent)


def _always(_agent: str):
    return lambda: True


def _rows(engine) -> list[Event]:
    with Session(engine) as session:
        return list(session.exec(select(Event).order_by(Event.id)).all())


def _count_commits(engine) -> list[int]:
    commits: list[int] = []
    sa.event.listen(engine, "commit", lambda conn: commits.append(1))
    return commits


# ── 5.1 severity_from_rules ───────────────────────────────────────────────────

def test_severity_from_rules_matches_determine_severity_for_path(mem_engine) -> None:
    with Session(mem_engine) as session:
        for pattern, sev in (
            ("/etc/*", RuleSeverity.critical),
            ("/etc/hosts", RuleSeverity.medium),
            ("!/etc/skip*", RuleSeverity.high),
            ("/srv/*", RuleSeverity.high),
        ):
            session.add(Rule(pattern=pattern, severity=sev, action=RuleAction.alert_only))
        session.commit()
        rules = list(session.exec(select(Rule)).all())
        for path in ("/etc/hosts", "/etc/skipme", "/srv/a", "/other/file"):
            assert severity_from_rules(path, rules) == determine_severity_for_path(path, session)
        # inclusion, negation and no match, explicitly
        assert severity_from_rules("/srv/a", rules) == RuleSeverity.high
        assert severity_from_rules("/etc/skipme", rules) == RuleSeverity.low
        assert severity_from_rules("/other/file", rules) == RuleSeverity.low


# ── 5.5 / 5.10 batch persistence ──────────────────────────────────────────────

def test_n_new_events_one_commit_ids_in_batch_order(mem_engine) -> None:
    commits = _count_commits(mem_engine)
    items = [_item(path=f"/f{i}") for i in range(5)]
    result = _ingest_batch(items, _always)
    assert [o.disposition for o in result.outcomes] == [IngestDisposition.persisted] * 5
    rows = _rows(mem_engine)
    assert [r.event_id for r in rows] == [i.event_data["event_id"] for i in items]
    assert [o.event.id for o in result.outcomes] == [r.id for r in rows]
    assert len(commits) == 1
    assert len(result.candidate_ms) == 5 and result.commit_ms >= 0 and result.ingest_db_ms >= 0


def test_two_pending_events_of_the_same_path_form_a_chain(mem_engine) -> None:
    first, second = _item(), _item()
    _ingest_batch([first, second], _always)
    a, b = _rows(mem_engine)
    assert (a.status, a.version) == (EventStatus.superseded, 1)  # version 0 incremented by 1
    assert (b.status, b.parent_event_id) == (EventStatus.pending, a.id)


def test_terminal_event_supersedes_the_pending_inserted_earlier_in_the_batch(mem_engine) -> None:
    _ingest_batch([_item(path="/etc/hosts"), _item(path="/etc/hosts", action="alert_only")], _always)
    a, b = _rows(mem_engine)
    assert a.status == EventStatus.superseded
    assert (b.status, b.parent_event_id) == (EventStatus.alert_only, a.id)


def test_repeated_event_id_in_the_batch_is_one_row_and_spends_no_token(mem_engine) -> None:
    spent: list[str] = []

    def accept_for(agent: str):
        def check() -> bool:
            spent.append(agent)
            return True
        return check

    dup = _item(event_id="same")
    result = _ingest_batch([dup, dup, _item(path="/other")], accept_for)
    assert [o.disposition for o in result.outcomes] == [
        IngestDisposition.persisted, IngestDisposition.duplicate, IngestDisposition.persisted,
    ]
    assert len(_rows(mem_engine)) == 2
    assert len(spent) == 2  # the repeated entry consumed nothing


def test_event_already_in_the_database_is_a_duplicate(mem_engine) -> None:
    item = _item()
    _ingest_event_outcome(item.event_data, item.received_at, item.detected_at)
    result = _ingest_batch([item], _always)
    assert result.outcomes[0].disposition == IngestDisposition.duplicate
    assert len(_rows(mem_engine)) == 1


def test_pending_in_the_database_is_superseded_by_the_first_batch_event(mem_engine) -> None:
    old = _item()
    _ingest_event_outcome(old.event_data, old.received_at, old.detected_at)
    _ingest_batch([_item()], _always)
    a, b = _rows(mem_engine)
    assert (a.status, a.version) == (EventStatus.superseded, 1)  # version 0 incremented by 1
    assert (b.status, b.parent_event_id) == (EventStatus.pending, a.id)


def test_race_with_a_still_pending_event_skips_the_candidate(mem_engine) -> None:
    old = _item()
    _ingest_event_outcome(old.event_data, old.received_at, old.detected_at)
    with patch.object(service_mod, "mark_superseded", return_value=False):
        result = _ingest_batch([_item()], _always)
    assert result.outcomes[0].disposition == IngestDisposition.supersede_race
    assert len(_rows(mem_engine)) == 1


def test_race_without_a_pending_event_inserts_independently(mem_engine) -> None:
    old = _item()
    _ingest_event_outcome(old.event_data, old.received_at, old.detected_at)

    def operator_approved_meanwhile(session, event_id, version):
        session.execute(sa.update(Event).where(Event.id == event_id).values(status=EventStatus.approved))
        return False

    with patch.object(service_mod, "mark_superseded", operator_approved_meanwhile):
        result = _ingest_batch([_item()], _always)
    assert result.outcomes[0].disposition == IngestDisposition.persisted
    a, b = _rows(mem_engine)
    assert a.status == EventStatus.approved
    assert (b.status, b.parent_event_id) == (EventStatus.pending, None)


def test_error_at_commit_rolls_back_and_refunds_the_tokens(mem_engine) -> None:
    refunded: dict[str, int] = {}
    items = [_item(path=f"/f{i}", agent="a1") for i in range(3)] + [_item(path="/g", agent="a2")]
    boom = OperationalError("COMMIT", {}, Exception("server closed the connection"))
    with patch.object(Session, "commit", side_effect=boom):
        with pytest.raises(OperationalError):
            _ingest_batch(items, _always, lambda agent, n: refunded.__setitem__(agent, n))
    assert _rows(mem_engine) == []
    assert refunded == {"a1": 3, "a2": 1}


def test_twelve_pending_events_of_one_path_compact_to_ten_superseded(mem_engine) -> None:
    result = _ingest_batch([_item() for _ in range(12)], _always)
    rows = _rows(mem_engine)
    assert sum(1 for r in rows if r.status == EventStatus.superseded) == 10
    assert sum(1 for r in rows if r.status == EventStatus.pending) == 1
    first_id = result.outcomes[0].event.id
    assert result.removed_event_ids == {first_id}
    assert first_id not in {r.id for r in rows}


def test_invalid_transition_in_the_batch_is_a_result_and_does_not_abort(mem_engine) -> None:
    items = [_item(path="/p"), _item(path="/p"), _item(path="/q")]
    calls = {"n": 0}
    real = service_mod.validate_transition

    def flaky(from_status, to_status):
        calls["n"] += 1
        raise InvalidTransitionError(from_status, to_status)

    with patch.object(service_mod, "validate_transition", flaky):
        result = _ingest_batch(items, _always)
    assert [o.disposition for o in result.outcomes] == [
        IngestDisposition.persisted, IngestDisposition.invalid_transition, IngestDisposition.persisted,
    ]
    assert [r.event_id for r in _rows(mem_engine)] == [
        items[0].event_data["event_id"], items[2].event_data["event_id"],
    ]
    assert real is not flaky


def test_per_event_path_still_propagates_invalid_transition(mem_engine) -> None:
    first = _item()
    _ingest_event_outcome(first.event_data, first.received_at, first.detected_at)
    second = _item()
    with patch.object(
        service_mod, "validate_transition",
        side_effect=InvalidTransitionError(EventStatus.pending, EventStatus.superseded),
    ):
        with pytest.raises(InvalidTransitionError):
            _ingest_event_outcome(second.event_data, second.received_at, second.detected_at)


def test_batch_reads_the_ruleset_once(mem_engine) -> None:
    with Session(mem_engine) as session:
        session.add(Rule(pattern="/srv/*", severity=RuleSeverity.critical, action=RuleAction.alert_only))
        session.commit()
    selects: list[str] = []
    sa.event.listen(
        mem_engine, "before_cursor_execute",
        lambda conn, cur, stmt, *a: selects.append(stmt) if "FROM rules" in stmt else None,
    )
    result = _ingest_batch([_item(path=f"/srv/f{i}") for i in range(4)], _always)
    assert len(selects) == 1
    assert {o.event.severity for o in result.outcomes} == {RuleSeverity.critical}
