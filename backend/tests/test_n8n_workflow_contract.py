"""
C46 — contract test between the n8n workflows and the emitted payload (D40/RN-134).

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

KNOWN LIMITATION: the extraction is a regex over `$json.body.X`, so it does not
cover bracket access or dynamically composed field names. Change 47 rewrites the
workflows and is the natural point to constrain the accepted access forms. The
mandatory negative test below guards the failure mode that matters most — a
silently empty extraction passing vacuously.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.modules.alerts.contract import ALERT_FIELDS, FORBIDDEN_FIELDS
from app.modules.alerts.models import Alert, AlertSeverity
from app.modules.alerts.service import _build_payload
from app.modules.events.models import Event, EventStatus

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "n8n" / "workflows"

# `{{ $json.body.severity }}`, `$json.body.event_id`, `$json.body.path || 'x'` …
_BODY_REF = re.compile(r"\$json\.body\.([A-Za-z_][A-Za-z0-9_]*)")

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


def extract_body_references() -> dict[str, set[str]]:
    """Map field name -> set of workflow filenames referencing it."""
    refs: dict[str, set[str]] = {}
    for path in _workflow_files():
        raw = path.read_text(encoding="utf-8")
        # Parse to fail loudly on malformed JSON rather than regexing garbage.
        json.loads(raw)
        for field in _BODY_REF.findall(raw):
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
    refs = extract_body_references()

    assert refs, (
        "the extractor produced no $json.body.<field> references. Either the "
        "workflow fixture is empty or the extraction pattern stopped matching. "
        "Fix the extractor — do not treat this as a passing contract."
    )


# ── Known divergence, owned by change 47 ─────────────────────────────────────
# These two are NOT payload fields the backend should add. RN-52 scopes n8n to
# the role of bounded router: which address an alert is mailed to, and whether a
# ticket goes to Jira or Linear, are administrator configuration inside n8n, not
# data the backend dictates. Adding them to the payload would put routing
# decisions back in the wrong system.
#
# So they get REMOVED from the workflows by change 47, not added here. Until
# then they are recorded explicitly rather than silently tolerated, and the
# ratchet below guarantees this list can only shrink.
KNOWN_UNBACKED_REFERENCES: frozenset[str] = frozenset({
    "recipient",          # email destination → n8n credential/config (change 47)
    "ticketing_system",   # jira|linear routing → n8n switch config (change 47)
})


def test_every_referenced_field_exists_in_the_payload() -> None:
    """Each field a workflow reads must be a field the backend actually emits."""
    payload = _reference_payload()
    refs = extract_body_references()

    missing = {
        field: sorted(files)
        for field, files in sorted(refs.items())
        if field not in payload and field not in KNOWN_UNBACKED_REFERENCES
    }

    assert not missing, "workflows read fields the backend does not emit:\n" + "\n".join(
        f"  $json.body.{field} — referenced by {', '.join(files)}"
        for field, files in missing.items()
    )


def test_known_divergence_list_can_only_shrink() -> None:
    """
    RATCHET — this is what stops the allowlist above from rotting into a
    permanent excuse.

    Every entry must still be a real, observed divergence. The moment change 47
    removes `recipient` / `ticketing_system` from the workflows, this test fails
    and forces the entry out of the allowlist too. An allowlist that nothing
    forces you to shrink is just a suppressed failure with better manners.
    """
    payload = _reference_payload()
    refs = extract_body_references()

    stale = sorted(
        field
        for field in KNOWN_UNBACKED_REFERENCES
        if field not in refs or field in payload
    )

    assert not stale, (
        "these entries of KNOWN_UNBACKED_REFERENCES are no longer divergent — "
        f"remove them from the allowlist: {stale}"
    )


def test_workflows_do_not_use_forbidden_field_names() -> None:
    """`file_path` was the architecture-doc outlier; RN-53 says `path`."""
    refs = extract_body_references()

    offenders = {f: sorted(files) for f, files in refs.items() if f in FORBIDDEN_FIELDS}

    assert not offenders, (
        "workflows use a non-canonical field name (RN-53 defines `path`): "
        f"{offenders}"
    )


def test_payload_fields_match_the_declared_contract() -> None:
    """Guards the other direction: the contract module and the builder agree."""
    assert set(_reference_payload()) == ALERT_FIELDS


def test_extractor_detects_an_unknown_field() -> None:
    """
    Proves the mechanism actually fails when it should, without mutating the
    real workflows: run the same extraction over a synthetic document.
    """
    synthetic = json.dumps(
        {"nodes": [{"parameters": {"subject": "={{ $json.body.definitely_not_a_field }}"}}]}
    )
    found = set(_BODY_REF.findall(synthetic))

    assert "definitely_not_a_field" in found
    assert "definitely_not_a_field" not in _reference_payload()


@pytest.mark.parametrize("expression", [
    "={{ $json.body.severity }}",
    "=[FIM] {{ $json.body.severity | upper }}: {{ $json.body.path }}",
    "={{ $json.body.recipient || 'security@example.com' }}",
])
def test_extractor_handles_the_expression_forms_in_use(expression: str) -> None:
    """Pins the shapes the current workflows actually use."""
    assert _BODY_REF.findall(expression), f"extractor missed: {expression}"
