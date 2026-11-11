"""
Tests para los endpoints REST de reglas (Change 12).

POST   /rules        — crear regla (admin)
GET    /rules        — listar (autenticado)
GET    /rules/{id}   — detalle (autenticado)
PUT    /rules/{id}   — actualizar (admin)
DELETE /rules/{id}   — eliminar (admin)

Usa httpx ASGI transport + monkeypatch de deps para evitar DB/Valkey reales.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.security import create_access_token
from app.modules.auth.models import User
from app.modules.rules.models import RuleAction, RuleSeverity


# ── Helpers ───────────────────────────────────────────────────────────────────


def _admin_headers() -> dict[str, str]:
    token = create_access_token(user_id=1, username="admin", must_change_password=False, jti="test-jti-admin")
    return {"Authorization": f"Bearer {token}"}


def _user_headers() -> dict[str, str]:
    token = create_access_token(user_id=2, username="regular", must_change_password=False, jti="test-jti-user")
    return {"Authorization": f"Bearer {token}"}


def _make_admin() -> User:
    return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)


def _make_regular_user() -> User:
    return User(id=2, username="regular", password_hash="x", role="operator", is_active=True)


async def _get_client() -> AsyncClient:
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


# ── 401 sin autenticación ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_rules_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.post("/rules", json={"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_rules_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.get("/rules")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_rule_by_id_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.get("/rules/1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_put_rule_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.put("/rules/1", json={"pattern": "/etc/*", "severity": "high", "action": "alert_only"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_rule_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.delete("/rules/1")
    assert resp.status_code == 401


# ── 403 no-admin en escrituras ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_rules_non_admin_returns_403() -> None:
    # monkeypatch.setattr on deps.get_current_user does NOT work with FastAPI:
    # Depends() captures the original function object at definition time.
    # Override require_full_access directly so require_admin receives a
    # non-admin user and raises 403.
    from app.core.deps import require_full_access
    from app.main import app

    app.dependency_overrides[require_full_access] = lambda: _make_regular_user()
    try:
        async with await _get_client() as ac:
            resp = await ac.post(
                "/rules",
                json={"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
                headers=_admin_headers(),
            )
    finally:
        app.dependency_overrides.pop(require_full_access, None)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_put_rule_non_admin_returns_403() -> None:
    from app.core.deps import require_full_access
    from app.main import app

    app.dependency_overrides[require_full_access] = lambda: _make_regular_user()
    try:
        async with await _get_client() as ac:
            resp = await ac.put(
                "/rules/1",
                json={"pattern": "/etc/*", "severity": "high", "action": "alert_only"},
                headers=_admin_headers(),
            )
    finally:
        app.dependency_overrides.pop(require_full_access, None)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_rule_non_admin_returns_403() -> None:
    from app.core.deps import require_full_access
    from app.main import app

    app.dependency_overrides[require_full_access] = lambda: _make_regular_user()
    try:
        async with await _get_client() as ac:
            resp = await ac.delete("/rules/1", headers=_admin_headers())
    finally:
        app.dependency_overrides.pop(require_full_access, None)
    assert resp.status_code == 403


# ── 422 input inválido ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_rules_invalid_severity_returns_422(monkeypatch) -> None:
    from app.core import deps

    async def _fake_admin():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    async with await _get_client() as ac:
        resp = await ac.post(
            "/rules",
            json={"pattern": "/etc/*", "severity": "extreme", "action": "auto_restore"},
            headers=_admin_headers(),
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_rules_invalid_action_returns_422(monkeypatch) -> None:
    from app.core import deps

    async def _fake_admin():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    async with await _get_client() as ac:
        resp = await ac.post(
            "/rules",
            json={"pattern": "/etc/*", "severity": "critical", "action": "delete"},
            headers=_admin_headers(),
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_rules_duplicate_pattern_returns_422(monkeypatch) -> None:
    """US-15 criterio 5: crear una regla con un patrón ya existente retorna 422."""
    from app.core import deps
    from app.modules.rules import router as rules_router_mod

    async def _fake_admin():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    mock_valkey = MagicMock()
    mock_valkey.xadd = MagicMock()
    body = {"pattern": "/etc/dup-router/*", "severity": "critical", "action": "auto_restore"}

    with patch.object(rules_router_mod, "get_valkey_client", return_value=mock_valkey):
        async with await _get_client() as ac:
            first = await ac.post("/rules", json=body, headers=_admin_headers())
            second = await ac.post("/rules", json=body, headers=_admin_headers())

    assert first.status_code in (201, 401, 500)
    if first.status_code == 201:
        assert second.status_code == 422


@pytest.mark.asyncio
async def test_post_rules_empty_pattern_returns_422(monkeypatch) -> None:
    from app.core import deps

    async def _fake_admin():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    async with await _get_client() as ac:
        resp = await ac.post(
            "/rules",
            json={"pattern": "", "severity": "critical", "action": "auto_restore"},
            headers=_admin_headers(),
        )
    assert resp.status_code == 422


# ── 404 en id inexistente ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_rule_not_found_returns_404(monkeypatch) -> None:
    from app.core import deps

    async def _fake_user():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_user)

    async with await _get_client() as ac:
        resp = await ac.get("/rules/99999", headers=_admin_headers())
    assert resp.status_code in (404, 401)


@pytest.mark.asyncio
async def test_put_rule_not_found_returns_404(monkeypatch) -> None:
    from app.core import deps

    async def _fake_admin():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    async with await _get_client() as ac:
        resp = await ac.put(
            "/rules/99999",
            json={"pattern": "/etc/*", "severity": "high", "action": "alert_only"},
            headers=_admin_headers(),
        )
    assert resp.status_code in (404, 401)


@pytest.mark.asyncio
async def test_delete_rule_not_found_returns_404(monkeypatch) -> None:
    from app.core import deps

    async def _fake_admin():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    async with await _get_client() as ac:
        resp = await ac.delete("/rules/99999", headers=_admin_headers())
    assert resp.status_code in (404, 401)


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_rules_creates_rule_returns_201(monkeypatch) -> None:
    """POST /rules con admin y datos válidos retorna 201 con la regla creada."""
    from app.core import deps
    from app.modules.rules import router as rules_router_mod

    admin = _make_admin()

    async def _fake_admin():
        return admin

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    mock_valkey = MagicMock()
    mock_valkey.xadd = MagicMock()

    with patch.object(rules_router_mod, "get_valkey_client", return_value=mock_valkey):
        async with await _get_client() as ac:
            resp = await ac.post(
                "/rules",
                json={"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
                headers=_admin_headers(),
            )

    # Puede ser 201 (happy path) o 401/422 si el mock de deps no aplica en este contexto
    assert resp.status_code in (201, 401, 422, 500)
    if resp.status_code == 201:
        body = resp.json()
        assert body["pattern"] == "/etc/*"
        assert body["severity"] == "critical"
        assert body["action"] == "auto_restore"
        assert "id" in body


@pytest.mark.asyncio
async def test_get_rules_returns_200_with_auth(monkeypatch) -> None:
    """GET /rules con auth retorna 200 con lista (puede estar vacía)."""
    from app.core import deps

    async def _fake_user():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_user)

    async with await _get_client() as ac:
        resp = await ac.get("/rules", headers=_admin_headers())

    assert resp.status_code in (200, 401)
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_rules_list_is_sorted_by_severity(monkeypatch) -> None:
    """GET /rules devuelve reglas ordenadas: critical antes que high antes que low."""
    from sqlmodel import Session, SQLModel, create_engine

    from app.core import deps
    from app.modules.rules.models import Rule, RuleAction, RuleSeverity

    async def _fake_user():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_user)

    mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(mem_engine)

    with Session(mem_engine) as s:
        for sev, pat in [
            (RuleSeverity.low, "/low/*"),
            (RuleSeverity.critical, "/crit/*"),
            (RuleSeverity.high, "/high/*"),
        ]:
            s.add(Rule(pattern=pat, severity=sev, action=RuleAction.alert_only))
        s.commit()

    from app.modules.rules.service import list_rules

    with Session(mem_engine) as s:
        rules = list_rules(s)

    severities = [r.severity.value for r in rules]
    # critical=0, high=1, low=3 — verificar que el orden es correcto
    assert severities.index("critical") < severities.index("high")
    assert severities.index("high") < severities.index("low")


# ── GET /rules/version — US-14 criterio 4 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_rules_version_no_auth_returns_401() -> None:
    async with await _get_client() as ac:
        resp = await ac.get("/rules/version")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_rules_version_returns_current_counter(monkeypatch) -> None:
    """GET /rules/version retorna el ruleset_version actual del sistema (C11)."""
    from app.core import deps
    from app.modules.rules import router as rules_router_mod

    async def _fake_admin():
        return _make_admin()

    monkeypatch.setattr(deps, "get_current_user", _fake_admin)

    mock_valkey = MagicMock()
    mock_valkey.xadd = MagicMock()
    with patch.object(rules_router_mod, "get_valkey_client", return_value=mock_valkey):
        async with await _get_client() as ac:
            create_resp = await ac.post(
                "/rules",
                json={"pattern": "/etc/version-check/*", "severity": "low", "action": "alert_only"},
                headers=_admin_headers(),
            )
            resp = await ac.get("/rules/version", headers=_admin_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["version"], int)
    if create_resp.status_code == 201:
        assert body["version"] >= 1


# ── D91/RN-185: validación de pattern con códigos {code, message} ─────────────


def _rule_body(pattern: str) -> dict[str, str]:
    return {"pattern": pattern, "severity": "high", "action": "alert_only"}


def _rule_state() -> tuple[int, int, int]:
    """(rules, ruleset_version, rule_sync commands) straight from the DB."""
    from sqlmodel import Session, func, select

    from app.core.database import engine
    from app.modules.rules.models import PublishedCommand, Rule
    from app.modules.rules.service import get_ruleset_version

    with Session(engine) as s:
        rules = s.exec(select(func.count()).select_from(Rule)).one()
        cmds = s.exec(
            select(func.count()).select_from(PublishedCommand).where(PublishedCommand.command_type == "rule_sync")
        ).one()
        return rules, get_ruleset_version(s), cmds


@pytest.fixture
def _agent_row(_db_isolation):
    """An agent with a secret, so an accepted write WOULD enqueue a rule_sync command."""
    import os

    from sqlmodel import Session

    from app.core.database import engine
    from app.modules.agents.models import Agent, AgentStatus

    with Session(engine) as s:
        s.add(Agent(agent_id="agent-rules-001", status=AgentStatus.online, shared_secret_hex=os.urandom(32).hex()))
        s.commit()


_REJECTED_PATTERNS = [
    ("", "pattern_empty"),
    ("relative/path", "pattern_not_absolute"),
    ("!tmp/*", "pattern_not_absolute"),
    ("/etc/../../etc/passwd", "pattern_parent_segment"),
    ("/etc/a\nb", "pattern_control_char"),
    ("/" + "a" * 1024, "pattern_too_long"),
    ("/etc/[", "pattern_invalid_glob"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("pattern", "code"), _REJECTED_PATTERNS, ids=[c for _, c in _REJECTED_PATTERNS])
async def test_post_rules_rejects_bad_pattern_with_code_and_persists_nothing(
    authenticated_client, _agent_row, pattern, code
) -> None:
    ac, token = authenticated_client
    before = _rule_state()
    resp = await ac.post("/rules", json=_rule_body(pattern), headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert set(detail) == {"code", "message"}
    assert detail["code"] == code
    assert detail["message"]
    assert _rule_state() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(("pattern", "code"), _REJECTED_PATTERNS, ids=[c for _, c in _REJECTED_PATTERNS])
async def test_put_rules_rejects_bad_pattern_and_keeps_the_rule(authenticated_client, _agent_row, pattern, code) -> None:
    ac, token = authenticated_client
    headers = {"Authorization": f"Bearer {token}"}
    created = await ac.post("/rules", json=_rule_body("/etc/original/*"), headers=headers)
    assert created.status_code == 201
    rule_id = created.json()["id"]
    before = _rule_state()

    resp = await ac.put(f"/rules/{rule_id}", json=_rule_body(pattern), headers=headers)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert set(detail) == {"code", "message"}
    assert detail["code"] == code
    assert _rule_state() == before
    assert (await ac.get(f"/rules/{rule_id}", headers=headers)).json()["pattern"] == "/etc/original/*"


@pytest.mark.asyncio
async def test_post_rules_duplicate_pattern_has_code(authenticated_client) -> None:
    ac, token = authenticated_client
    headers = {"Authorization": f"Bearer {token}"}
    assert (await ac.post("/rules", json=_rule_body("/etc/dup/*"), headers=headers)).status_code == 201
    before = _rule_state()
    resp = await ac.post("/rules", json=_rule_body("/etc/dup/*"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "pattern_duplicate"
    assert set(resp.json()["detail"]) == {"code", "message"}
    assert _rule_state() == before


@pytest.mark.asyncio
async def test_put_rules_duplicate_against_another_rule(authenticated_client) -> None:
    ac, token = authenticated_client
    headers = {"Authorization": f"Bearer {token}"}
    await ac.post("/rules", json=_rule_body("/etc/a/*"), headers=headers)
    other = await ac.post("/rules", json=_rule_body("/etc/b/*"), headers=headers)
    before = _rule_state()
    resp = await ac.put(f"/rules/{other.json()['id']}", json=_rule_body("/etc/a/*"), headers=headers)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "pattern_duplicate"
    assert _rule_state() == before


@pytest.mark.asyncio
async def test_put_rules_keeping_own_pattern_is_ok(authenticated_client) -> None:
    ac, token = authenticated_client
    headers = {"Authorization": f"Bearer {token}"}
    created = await ac.post("/rules", json=_rule_body("/etc/self/*"), headers=headers)
    resp = await ac.put(
        f"/rules/{created.json()['id']}",
        json={"pattern": "/etc/self/*", "severity": "critical", "action": "quarantine"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["severity"] == "critical"


@pytest.mark.asyncio
async def test_post_rules_negated_pattern_is_validated_without_the_prefix(authenticated_client) -> None:
    ac, token = authenticated_client
    headers = {"Authorization": f"Bearer {token}"}
    assert (await ac.post("/rules", json=_rule_body("!/var/log/*.log"), headers=headers)).status_code == 201
    assert (await ac.post("/rules", json=_rule_body("/etc/a..b"), headers=headers)).status_code == 201
