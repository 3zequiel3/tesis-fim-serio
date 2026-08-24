"""
C46 — canonical notification payload (D40/RN-134).

RN-53 requires the notification to carry the event id, path, severity, the
action taken, the causing process context (process_pid / process_uid /
process_exe) and both timestamps. Before this change `_build_payload` emitted
seven fields and none of the forensic ones — the single most valuable datum a
FIM produces never left the system.

These tests pin the shape itself. The companion suite
(test_n8n_workflow_contract.py) pins the shape against what the n8n workflows
actually read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.alerts.contract import (
    ALERT_FIELDS,
    FORBIDDEN_FIELDS,
    SCHEMA_VERSION,
)
from app.modules.alerts.models import Alert, AlertSeverity
from app.modules.alerts.service import _build_payload
from app.modules.events.models import Event, EventStatus

_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


def _event(**overrides) -> Event:
    defaults = dict(
        id=7,
        event_id="e4f1c2a0-0000-4000-8000-000000000001",
        agent_id="agent-01",
        path="/etc/passwd",
        status=EventStatus.auto_restored,
        is_symlink=False,
        action_failed=False,
        process_pid=4242,
        process_uid=0,
        process_exe="/usr/bin/curl",
        detected_at=_NOW,
        received_at=_NOW + timedelta(milliseconds=120),
    )
    defaults.update(overrides)
    return Event(**defaults)


def _alert(**overrides) -> Alert:
    defaults = dict(
        id=123,
        event_id=7,
        severity=AlertSeverity.critical,
        created_at=_NOW + timedelta(milliseconds=200),
    )
    defaults.update(overrides)
    return Alert(**defaults)


def test_payload_carries_every_contract_field() -> None:
    payload = _build_payload(_alert(), _event())

    assert set(payload) == ALERT_FIELDS, (
        "the emitted payload must match the contract exactly — extra or missing "
        "keys are how the n8n contract drifted in the first place"
    )


def test_payload_satisfies_rn53() -> None:
    """The fields RN-53 names explicitly, which were all missing before C46."""
    payload = _build_payload(_alert(), _event())

    assert payload["action_taken"] == "auto_restore"
    assert payload["process_pid"] == 4242
    assert payload["process_uid"] == 0
    assert payload["process_exe"] == "/usr/bin/curl"
    assert payload["received_at"] == (_NOW + timedelta(milliseconds=120)).isoformat()


def test_envelope_is_flat_not_nested() -> None:
    """D-1: nesting under `data` would break the Battery 4 receiver and the workflows."""
    payload = _build_payload(_alert(), _event())

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["type"] == "alert"
    assert "data" not in payload
    assert payload["path"] == "/etc/passwd", "path must be reachable at the top level"


def test_path_is_canonical_name() -> None:
    """RN-53 says `path`; `file_path` was an architecture-doc outlier."""
    payload = _build_payload(_alert(), _event())

    assert "path" in payload
    for forbidden in FORBIDDEN_FIELDS:
        assert forbidden not in payload


def test_absent_process_context_is_null_not_omitted() -> None:
    """A missing key and a null value are different things to a workflow expression."""
    event = _event(process_pid=None, process_uid=None, process_exe=None)
    payload = _build_payload(_alert(), event)

    for key in ("process_pid", "process_uid", "process_exe"):
        assert key in payload, f"{key} must be present even when unknown"
        assert payload[key] is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (EventStatus.pending, None),
        (EventStatus.auto_restored, "auto_restore"),
        (EventStatus.quarantined, "quarantine"),
        (EventStatus.alert_only, "alert_only"),
    ],
)
def test_action_taken_is_not_a_second_copy_of_status(
    status: EventStatus, expected: str | None
) -> None:
    """
    D35/RN-129 derives status from the agent's action, but the two are not
    synonyms: a `pending` event has no action taken, it has a decision awaiting
    a human. Emitting status twice under two names would mislead the workflow
    author into reporting "pending" as an executed remediation.
    """
    payload = _build_payload(_alert(), _event(status=status))

    assert payload["status"] == status.value
    assert payload["action_taken"] == expected


def test_notification_id_differs_between_notifications() -> None:
    first = _build_payload(_alert(id=1), _event())
    second = _build_payload(_alert(id=2), _event())

    assert first["notification_id"] != second["notification_id"]


def test_notification_id_is_built_once_per_notify_event() -> None:
    """
    D41/RN-135 depends on the id being stable across the retry ladder. The
    invariant is structural: `notify_event` calls `_build_payload` once, outside
    the loop. This test pins that structure so a refactor that moves the call
    inside the loop fails here instead of silently breaking deduplication.
    """
    import inspect

    from app.modules.alerts import service

    source = inspect.getsource(service.notify_event)
    build_line = next(
        i for i, line in enumerate(source.splitlines()) if "_build_payload(" in line
    )
    loop_line = next(
        i for i, line in enumerate(source.splitlines()) if "for attempt in range" in line
    )

    assert build_line < loop_line, (
        "_build_payload must be called before the retry loop; calling it inside "
        "would mint a new notification_id per attempt"
    )
