"""
Error body contract (D90/RN-184, change backend-input-validation-hardening).

Every error is FastAPI's ``{"detail": ...}``. The errors introduced or modified by
this change carry ``detail == {"code": <snake_case str>, "message": <Spanish str>}``
(plus ``index`` for ``watch_path_*``) and NO ``code`` at the body root. The errors
that already emitted an object keep their ``code`` and extra fields.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _assert_code_message(body: dict, code: str, *, extra: frozenset[str] = frozenset()) -> None:
    assert set(body) == {"detail"}, "no `code` (or anything else) at the body root"
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert set(detail) == {"code", "message"} | extra
    assert detail["code"] == code
    assert _CODE_RE.match(detail["code"])
    assert isinstance(detail["message"], str) and detail["message"].strip()
    # Spanish copy, not one of the former English texts.
    for english in ("Incorrect", "must not be empty", "duplicate pattern", "Password must", "Too many"):
        assert english not in detail["message"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── rules ─────────────────────────────────────────────────────────────────────

_RULE_CASES = [
    ("", "pattern_empty"),
    ("rel", "pattern_not_absolute"),
    ("/a/../b", "pattern_parent_segment"),
    ("/a\tb", "pattern_control_char"),
    ("/" + "a" * 1024, "pattern_too_long"),
    ("/a/[", "pattern_invalid_glob"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("pattern", "code"), _RULE_CASES, ids=[c for _, c in _RULE_CASES])
async def test_rule_errors_have_code_and_message(authenticated_client, pattern, code):
    ac, token = authenticated_client
    resp = await ac.post(
        "/rules",
        json={"pattern": pattern, "severity": "low", "action": "alert_only"},
        headers=_bearer(token),
    )
    assert resp.status_code == 422
    _assert_code_message(resp.json(), code)


@pytest.mark.asyncio
async def test_rule_duplicate_has_code_and_message(authenticated_client):
    ac, token = authenticated_client
    body = {"pattern": "/dup/*", "severity": "low", "action": "alert_only"}
    await ac.post("/rules", json=body, headers=_bearer(token))
    resp = await ac.post("/rules", json=body, headers=_bearer(token))
    assert resp.status_code == 422
    _assert_code_message(resp.json(), "pattern_duplicate")


# ── watch_paths ───────────────────────────────────────────────────────────────

_WATCH_CASES = [
    ([], "watch_paths_empty", False),
    ([f"/p{i}" for i in range(65)], "watch_paths_too_many", False),
    (["rel"], "watch_path_not_absolute", True),
    (["/a/.."], "watch_path_parent_segment", True),
    (["/a\x00"], "watch_path_control_char", True),
    (["/" + "a" * 1024], "watch_path_too_long", True),
    (["/a", "/a/"], "watch_path_duplicate", True),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("paths", "code", "has_index"), _WATCH_CASES, ids=[c for _, c, _ in _WATCH_CASES])
async def test_watch_path_errors_have_code_message_and_index(authenticated_client, paths, code, has_index):
    ac, token = authenticated_client
    with Session(engine) as s:
        s.add(Agent(agent_id="agent-contract", status=AgentStatus.online, shared_secret_hex=os.urandom(32).hex()))
        s.commit()
    resp = await ac.post("/agents/agent-contract/config", json={"watch_paths": paths}, headers=_bearer(token))
    assert resp.status_code == 422
    _assert_code_message(resp.json(), code, extra=frozenset({"index"}) if has_index else frozenset())
    assert isinstance(resp.json()["detail"].get("index", 0), int)


# ── login and change-password ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_invalid_credentials_contract(client):
    resp = await client.post("/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401
    _assert_code_message(resp.json(), "invalid_credentials")


@pytest.mark.asyncio
async def test_change_password_error_contracts(authenticated_client):
    ac, token = authenticated_client
    from tests.conftest import _FORCED_CHANGE_NEW_PASSWORD as current

    cases = [
        ({"current_password": "nope-nope-nope", "new_password": "AnotherValidPass9!"}, 401, "current_password_invalid"),
        ({"current_password": current, "new_password": "short"}, 422, "password_policy"),
        ({"current_password": current, "new_password": current}, 422, "password_reuse"),
    ]
    for payload, status_code, code in cases:
        resp = await ac.post("/users/change-password", json=payload, headers=_bearer(token))
        assert resp.status_code == status_code, resp.text
        _assert_code_message(resp.json(), code)


# ── errors that already emitted an object keep their shape ────────────────────


@pytest.mark.asyncio
async def test_pending_events_exist_keeps_code_and_count(authenticated_client):
    ac, token = authenticated_client
    with Session(engine) as s:
        s.add(Agent(agent_id="agent-pending", status=AgentStatus.online, shared_secret_hex=os.urandom(32).hex()))
        s.commit()
        s.add(
            Event(
                event_id=str(uuid.uuid4()),
                hash_detected="a" * 64,
                hash_expected="b" * 64,
                detected_at=datetime.now(timezone.utc),
                received_at=datetime.now(timezone.utc),
                agent_id="agent-pending",
                path="/etc/passwd",
                status=EventStatus.pending,
                event_type="file_modified",
            )
        )
        s.commit()
    resp = await ac.post("/agents/agent-pending/rescan", json={"force": False}, headers=_bearer(token))
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "pending_events_exist", "count": 1}


@pytest.mark.asyncio
async def test_other_existing_codes_are_preserved(authenticated_client, monkeypatch):
    from app.modules.actions import router as actions_router
    from app.modules.actions import service as actions_service
    from app.modules.events import router as events_router

    ac, token = authenticated_client

    def _raise(exc):
        def _inner(*args, **kwargs):
            raise exc

        return _inner

    monkeypatch.setattr(actions_router, "_approve_single", _raise(actions_service.AbsentConfirmationRequired(1)))
    resp = await ac.post("/actions/approve", json={"event_id": 1, "version": 1}, headers=_bearer(token))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "absent_confirmation_required"

    for exc, code in (
        (actions_service.QuarantineNotReleasable(1), "quarantine_not_releasable"),
        (actions_service.ReleaseInProgress(1), "release_in_progress"),
    ):
        monkeypatch.setattr(events_router, "release_quarantine_single", _raise(exc))
        resp = await ac.post(
            "/events/1/quarantine/release",
            json={"mode": "restore_original", "reason": "test"},
            headers=_bearer(token),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == code
