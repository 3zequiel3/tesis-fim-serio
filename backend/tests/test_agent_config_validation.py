"""
POST /agents/{id}/config — watch_paths validation (D91/RN-185, D90/RN-184).

Every rejection is a 422 with ``detail = {code, message[, index]}`` and happens
before any write: ``agents.watch_paths``, ``ruleset_version``, ``audit_log``,
the outbox and the ``commands`` stream stay untouched.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, func, select

from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.audit.models import AuditLog
from app.modules.rules.models import PublishedCommand
from app.modules.rules.service import get_ruleset_version

AGENT_ID = "agent-cfg-001"


@pytest.fixture
def valkey_mock():
    from app.core.valkey import get_valkey_client
    from app.main import app

    mock = MagicMock()
    app.dependency_overrides[get_valkey_client] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_valkey_client, None)


@pytest.fixture
def agent_row(authenticated_client):
    with Session(engine) as s:
        s.add(
            Agent(
                agent_id=AGENT_ID,
                status=AgentStatus.online,
                shared_secret_hex=os.urandom(32).hex(),
                watch_paths=["/etc"],
            )
        )
        s.commit()


def _snapshot() -> tuple:
    with Session(engine) as s:
        agent = s.get(Agent, AGENT_ID)
        audits = s.exec(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "agent_config")
        ).one()
        cmds = s.exec(select(func.count()).select_from(PublishedCommand)).one()
        return list(agent.watch_paths), get_ruleset_version(s), audits, cmds


async def _post(authenticated_client, paths):
    ac, token = authenticated_client
    return await ac.post(
        f"/agents/{AGENT_ID}/config",
        json={"watch_paths": paths},
        headers={"Authorization": f"Bearer {token}"},
    )


_CASES = [
    ([], "watch_paths_empty", None),
    ([f"/p{i}" for i in range(65)], "watch_paths_too_many", None),
    (["/etc", "var/www"], "watch_path_not_absolute", 1),
    (["/srv/../etc"], "watch_path_parent_segment", 0),
    (["/etc", "/a\nb"], "watch_path_control_char", 1),
    (["/" + "a" * 1024], "watch_path_too_long", 0),
    (["/etc", "/etc/"], "watch_path_duplicate", 1),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("paths", "code", "index"), _CASES, ids=[c for _, c, _ in _CASES])
async def test_rejected_config_changes_nothing(authenticated_client, agent_row, valkey_mock, paths, code, index):
    before = _snapshot()

    resp = await _post(authenticated_client, paths)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == code
    assert detail["message"]
    if index is None:
        assert set(detail) == {"code", "message"}
    else:
        assert detail["index"] == index
        assert set(detail) == {"code", "message", "index"}
    assert _snapshot() == before
    valkey_mock.xadd.assert_not_called()


@pytest.mark.asyncio
async def test_nonexistent_path_is_accepted(authenticated_client, agent_row, valkey_mock):
    before_version = _snapshot()[1]

    resp = await _post(authenticated_client, ["/opt/no-existe"])

    assert resp.status_code == 200
    assert resp.json()["watch_paths"] == ["/opt/no-existe"]
    paths, version, audits, _ = _snapshot()
    assert paths == ["/opt/no-existe"]
    assert version == before_version + 1
    assert audits == 1
    valkey_mock.xadd.assert_called_once()


@pytest.mark.asyncio
async def test_valid_list_with_boundary_sizes_is_accepted(authenticated_client, agent_row, valkey_mock):
    paths = [f"/p{i}" for i in range(63)] + ["/" + "a" * 1023]
    resp = await _post(authenticated_client, paths)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unknown_agent_with_valid_list_is_404(authenticated_client, valkey_mock):
    ac, token = authenticated_client
    resp = await ac.post(
        "/agents/unknown-agent/config",
        json={"watch_paths": ["/etc"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
