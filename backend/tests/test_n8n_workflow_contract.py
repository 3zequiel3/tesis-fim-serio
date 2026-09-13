"""
C46 — contract test between the n8n workflows and the emitted payload (D40/RN-134).
Rewritten for change 52 (D44/RN-138): the router now receives the payload as
`$json.body.<field>` and forwards it to each sub-flow under the `payload` key,
so sub-flows read `$json.payload.<field>` (or, after a hop through another
node, `.json.payload.<field>` via a `$('<node>').item...` reference).

THIS IS THE TEST THAT WOULD HAVE CAUGHT THE WHOLE DIVERGENCE.

`openspec/specs/backend-notifications/spec.md` specified retry, cascade and DLQ
behaviour and said nothing about the payload. With no requirement and no test,
the two ends drifted freely: the workflows read `body.status`, `body.recipient`
and `body.ticketing_system`, none of which the backend has ever emitted, so
those fields rendered empty in every channel and the Jira/Linear routing always
fell through to its default. Nobody noticed, because nothing ever compared the
two sides.

The fixture is the real `n8n/workflows/*.json`, not a copy. That is deliberate:
a separate fixture file could itself drift from the workflows it claims to
represent, which is precisely the failure mode this test exists to prevent. The
consumer IS a versioned declarative artifact in this repo, so it can be read
directly.

KNOWN LIMITATION: the extraction is a regex over the two accepted access
forms, so it does not cover bracket access or dynamically composed field
names. The mandatory negative test below guards the failure mode that matters
most — a silently empty extraction passing vacuously.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.modules.alerts.contract import FORBIDDEN_FIELDS, NOTIFICATION_FIELDS
from app.modules.alerts.models import Alert, AlertSeverity
from app.modules.alerts.service import _build_payload
from app.modules.events.models import Event, EventStatus

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "n8n" / "workflows"

# `$json.body.severity`, `$json.body.path || 'x'` — the router, which receives
# the payload straight from the webhook. Scanned ONLY in the router file (see
# `extract_references` below): sub-flows also produce `$json.body.<field>`
# text, but there it names the BODY OF AN HTTP RESPONSE (Slack/Jira/Linear
# API calls), an unrelated meaning that happens to share n8n's own field name
# for a full-response `httpRequest` output — not the notification payload.
_BODY_REF = re.compile(r"\$json\.body\.([A-Za-z_][A-Za-z0-9_]*)")

# `$json.payload.event_id`, `$('Load ticketing config').item.json.payload.severity`
# — any sub-flow invoked via `Execute Workflow Trigger`, which receives the
# payload wrapped under the `payload` key (D44/RN-138): either the plain form
# (`$json.payload.<field>`) or the node-reference form, which always has a
# `.` immediately before `json` (`...item.json.payload.<field>`).
_PAYLOAD_REF = re.compile(r"[$.]json\.payload\.([A-Za-z_][A-Za-z0-9_]*)")

# Sub-flow files: anything with an `Execute Workflow Trigger` node and no
# webhook (the router is the only file with a webhook — enforced by
# test_n8n_workflow_lint.py). Recomputed per file rather than hardcoded so
# adding a new sub-flow file is automatically covered.
_SUBFLOW_TRIGGER_TYPE = "n8n-nodes-base.executeWorkflowTrigger"

_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


def _reference_payload() -> dict:
    event = Event(
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
    alert = Alert(
        id=123,
        event_id=7,
        severity=AlertSeverity.critical,
        created_at=_NOW + timedelta(milliseconds=200),
    )
    return _build_payload(alert, event)


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.json"))


def _load(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)


def _is_subflow(workflow: dict) -> bool:
    return any(node.get("type") == _SUBFLOW_TRIGGER_TYPE for node in workflow.get("nodes", []))


def extract_references() -> dict[str, set[str]]:
    """Map field name -> set of workflow filenames referencing it.

    `_BODY_REF` is scanned only in the router (the one file with a webhook
    node — enforced by `test_n8n_workflow_lint.py`): elsewhere `$json.body`
    names an HTTP response, not the notification payload. `_PAYLOAD_REF` is
    scanned only in sub-flow files (files with an `Execute Workflow Trigger`
    node), which is the only place `payload` is a meaningful key."""
    refs: dict[str, set[str]] = {}
    for path in _workflow_files():
        raw = path.read_text(encoding="utf-8")
        workflow = json.loads(raw)  # fail loudly on malformed JSON rather than regexing garbage
        pattern = _PAYLOAD_REF if _is_subflow(workflow) else _BODY_REF
        for field in pattern.findall(raw):
            refs.setdefault(field, set()).add(path.name)
    return refs


def test_workflows_directory_is_present() -> None:
    assert WORKFLOWS_DIR.is_dir(), f"expected workflows at {WORKFLOWS_DIR}"
    assert _workflow_files(), "no workflow JSON files found — the fixture is empty"


def test_extraction_is_not_vacuous() -> None:
    """
    MANDATORY NEGATIVE CASE.

    Without this, emptying the fixture — or breaking the regex — turns the
    contract test below green while it verifies nothing at all. A test that
    passes on zero inputs is worse than no test: it reports safety it does not
    provide. This is the same lesson change 45 paid for with `contracts/`.
    """
    refs = extract_references()

    assert refs, (
        "the extractor produced no $json.body.<field> nor .json.payload.<field> "
        "references. Either the workflow fixture is empty or the extraction "
        "pattern stopped matching. Fix the extractor — do not treat this as a "
        "passing contract."
    )


# The ratchet below MUST stay empty: change 52 removed `recipient` and
# `ticketing_system` from every workflow (RN-52 — destination and ticketing
# system are n8n deployment configuration, D58/RN-152, never payload data).
KNOWN_UNBACKED_REFERENCES: frozenset[str] = frozenset()


def test_every_referenced_field_exists_in_the_payload() -> None:
    """Each field a workflow reads must be a field the backend actually
    emits, for at least one of the two notification types (`alert` or
    `health_change`) — both travel through the same webhook and the same
    `Execute Workflow` calls."""
    refs = extract_references()

    missing = {
        field: sorted(files)
        for field, files in sorted(refs.items())
        if field not in NOTIFICATION_FIELDS and field not in KNOWN_UNBACKED_REFERENCES
    }

    assert not missing, "workflows read fields the backend does not emit:\n" + "\n".join(
        f"  {field} — referenced by {', '.join(files)}" for field, files in missing.items()
    )


def test_known_divergence_list_is_empty() -> None:
    """
    RATCHET — change 52 closed the divergence change 47 tracked
    (`recipient`, `ticketing_system`). If a future change adds an entry here,
    it must be a real, currently observed divergence, not a permanent excuse.
    """
    assert not KNOWN_UNBACKED_REFERENCES, (
        "KNOWN_UNBACKED_REFERENCES must stay empty — RN-52 scopes n8n to a "
        f"bounded router; got: {sorted(KNOWN_UNBACKED_REFERENCES)}"
    )


def test_workflows_do_not_use_forbidden_field_names() -> None:
    """`file_path` was the architecture-doc outlier; RN-53 says `path`."""
    refs = extract_references()

    offenders = {f: sorted(files) for f, files in refs.items() if f in FORBIDDEN_FIELDS}

    assert not offenders, (
        "workflows use a non-canonical field name (RN-53 defines `path`): "
        f"{offenders}"
    )


def test_payload_fields_match_the_declared_contract() -> None:
    """Guards the other direction: the contract module and the builder agree."""
    from app.modules.alerts.contract import ALERT_FIELDS

    assert set(_reference_payload()) == ALERT_FIELDS


def test_every_subflow_produces_at_least_one_reference() -> None:
    """A sub-flow that reads nothing from `payload` could quietly fall out of
    the contract by using an access form the extractor does not recognize."""
    for path in _workflow_files():
        workflow = _load(path)
        if not _is_subflow(workflow):
            continue
        raw = path.read_text(encoding="utf-8")
        found = _PAYLOAD_REF.findall(raw)
        assert found, f"sub-flow {path.name} produced no $json.payload.<field> references"


def test_extractor_detects_an_unknown_field() -> None:
    """
    Proves the mechanism actually fails when it should, without mutating the
    real workflows: run the same extraction over synthetic documents for both
    access forms.
    """
    synthetic_body = json.dumps(
        {"nodes": [{"parameters": {"subject": "={{ $json.body.definitely_not_a_field }}"}}]}
    )
    synthetic_payload = json.dumps(
        {"nodes": [{"parameters": {"subject": "={{ $json.payload.definitely_not_a_field }}"}}]}
    )

    found_body = set(_BODY_REF.findall(synthetic_body))
    found_payload = set(_PAYLOAD_REF.findall(synthetic_payload))

    assert "definitely_not_a_field" in found_body
    assert "definitely_not_a_field" in found_payload
    assert "definitely_not_a_field" not in _reference_payload()


@pytest.mark.parametrize("expression", [
    "={{ $json.body.type === 'health_change' ? 1 : 0 }}",
    "={{ $json.body.type }}",
])
def test_extractor_handles_router_body_forms(expression: str) -> None:
    """Pins the shapes the router actually uses."""
    assert _BODY_REF.findall(expression), f"extractor missed: {expression}"


@pytest.mark.parametrize("expression", [
    "={{ ($json.payload.severity || 'notice').toUpperCase() }}",
    "={{ $('Load ticketing config').item.json.payload.event_id }}",
])
def test_extractor_handles_subflow_payload_forms(expression: str) -> None:
    """Pins the shapes the sub-flows actually use, including the
    node-reference form `$('<node>').item.json.payload.<field>`."""
    assert _PAYLOAD_REF.findall(expression), f"extractor missed: {expression}"


def test_router_whole_object_passthrough_produces_no_field_reference() -> None:
    """The router wraps the *entire* original payload under `payload` for
    each sub-flow call (`={{ $('Receive FIM alert').item.json.body }}`)
    rather than rebuilding it field by field — by design, this produces no
    `$json.payload.<field>` reference at all, and correctly so: the router
    itself is not a sub-flow (no `Execute Workflow Trigger`) and is exempt
    from `test_every_subflow_produces_at_least_one_reference`."""
    expression = "={{ $('Receive FIM alert').item.json.body }}"
    assert not _PAYLOAD_REF.findall(expression)
