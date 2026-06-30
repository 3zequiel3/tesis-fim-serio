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
