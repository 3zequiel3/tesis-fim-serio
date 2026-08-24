"""
Canonical notification payload contract (C46 — D40/RN-134).

Single source of truth for the shape the backend sends to n8n. Both
`_build_payload` (alerts/service.py) and the workflow contract test read from
here, so a field cannot exist in one and not the other.

WHY THIS MODULE EXISTS
    `openspec/specs/backend-notifications/spec.md` specified retry, cascade and
    DLQ behaviour — and nothing about the payload. A contract that no spec
    describes and no test verifies can only drift, and it did: the emitted
    payload was missing the action taken, the causing process context
    (`process_pid`, `process_uid`, `process_exe`) and `received_at`, all of
    which RN-53 requires. The process context is the highest-value forensic
    datum a FIM produces and it never left the system.

FLAT ENVELOPE, NOT NESTED (D-1 of the change design)
    `schema_version`, `notification_id` and `type` are SIBLINGS of the data
    fields, never parents. The tidier `{"type": ..., "data": {...}}` shape was
    rejected on evidence, not taste:
      - scripts/receptor_webhook.py reads alert_id/event_id/severity/path at the
        TOP level. Nesting would null those columns in the Chapter 5 Battery 4
        JSONL and force the whole battery to be re-run.
      - The n8n workflows read `$json.body.<field>` flat. Nesting would mean
        rewriting every expression, dragging change 47 into this one.
    `schema_version` is present from day one so a future move to a nested shape
    is a versioned migration rather than a silent break.
"""

from __future__ import annotations

from app.modules.events.models import EventStatus

# Bump on a REMOVAL or RENAME of a field. Purely additive changes do not bump.
SCHEMA_VERSION = 1

NOTIFICATION_TYPE_ALERT = "alert"
NOTIFICATION_TYPE_HEALTH_CHANGE = "health_change"

# Envelope keys, shared by every notification type.
ENVELOPE_FIELDS: tuple[str, ...] = (
    "schema_version",
    "notification_id",
    "type",
)

# Data fields of an `alert` notification. RN-53 requires event_id, path,
# severity, the action taken, the causing process context and both timestamps.
ALERT_DATA_FIELDS: tuple[str, ...] = (
    "alert_id",
    "event_id",
    "path",
    "severity",
    "status",
    "action_taken",
    "action_failed",
    "is_symlink",
    "agent_id",
    "process_pid",
    "process_uid",
    "process_exe",
    "detected_at",
    "received_at",
    "alert_created_at",
)

ALERT_FIELDS: frozenset[str] = frozenset(ENVELOPE_FIELDS + ALERT_DATA_FIELDS)

# The canonical name for the monitored path is `path` — that is what RN-53
# states, what the code has always emitted and what all three workflows read.
# `file_path` appeared only in an architecture-doc example and was the outlier;
# it is now aligned. Guarded by the contract test so it cannot come back.
FORBIDDEN_FIELDS: frozenset[str] = frozenset({"file_path"})


# `status` and `action_taken` are NOT synonyms, even though D35/RN-129 derives
# the status from the agent's `action`. A `pending` event has no action taken —
# it has a decision awaiting a human. Emitting the same value under two names
# would be noise for whoever writes the n8n workflow, so the mapping is explicit
# and `action_taken` is null precisely when no action was executed.
_STATUS_TO_ACTION: dict[EventStatus, str | None] = {
    EventStatus.pending: None,
    EventStatus.auto_restored: "auto_restore",
    EventStatus.quarantined: "quarantine",
    EventStatus.alert_only: "alert_only",
    EventStatus.approved: "approved",
    EventStatus.rejected: "rejected",
    EventStatus.superseded: None,
}


def action_taken_for(status: EventStatus) -> str | None:
    """Executed action for an event status, or None when none was executed."""
    return _STATUS_TO_ACTION.get(status)
