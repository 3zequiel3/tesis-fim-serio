"""
Root conftest for the FIM backend test suite.

Schema, seeding, and per-test isolation are owned by this conftest — NOT by
the FastAPI lifespan. httpx.AsyncClient + ASGITransport does NOT execute the
app's startup/shutdown hooks, so create_all and seed_admin must be driven
explicitly here.

Canonical run (bring up ephemeral backing services first, then):
  docker run --rm -d --name fim-test-db \\
    -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fim_test \\
    -p 5432:5432 postgres:18.3
  docker run --rm -d --name fim-test-valkey -p 6379:6379 valkey/valkey:9.0.3

  uv run pytest          # from backend/

Default DATABASE_URL: postgresql+psycopg://fim:test@localhost:5432/fim_test
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# ── Canonical env vars — set BEFORE any app module import ────────────────────
# Settings() is instantiated at import time; these must be in the environment
# before the first import of app.core.config (or any module that imports it).
# Use direct assignment (not setdefault) so our values always win.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ["VALKEY_URL"] = "valkey://localhost:6379"
os.environ["JWT_SECRET_CURRENT"] = "test-secret-current-32-chars-xxxxx"
os.environ["JWT_SECRET_PREVIOUS"] = ""
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "AdminPassword123!"
os.environ["ADMIN_EMAIL"] = os.environ.get("ADMIN_EMAIL", "admin@fim.local")
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:5173"


# ── Schema — once per session ─────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    """Create all SQLModel tables on the test Postgres engine once per session."""
    from app.core.database import engine
    from sqlmodel import SQLModel

    # Importing app.main registers all domain models with SQLModel.metadata.
    import app.main  # noqa: F401

    SQLModel.metadata.create_all(engine)
    yield


# ── Admin seed helper ─────────────────────────────────────────────────────────

def _seed_admin_impl() -> None:
    """Insert the canonical test admin into the real Postgres engine.

    Mirrors seed_admin() semantics and asserts must_change_password=True
    (RN-62, RN-100/W20 — first login must trigger forced password change).
    """
    from app.core.config import settings
    from app.core.database import engine
    from app.core.security import hash_password
    from app.modules.auth.models import User
    from sqlmodel import Session

    with Session(engine) as session:
        admin = User(
            username=settings.admin_username,
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password.get_secret_value()),
            role="admin",
            is_active=True,
            must_change_password=True,  # RN-62, RN-100/W20
        )
        session.add(admin)
        session.commit()


# ── Per-test isolation — TRUNCATE + reseed ────────────────────────────────────

@pytest.fixture(autouse=True)
def _db_isolation(_create_schema):
    """Per-test isolation: TRUNCATE all tables and reseed the canonical admin.

    Uses RESTART IDENTITY CASCADE so FK constraints and sequences are clean.
    Pattern B/C tests rely on this; Pattern A tests (in-memory SQLite) are
    unaffected — TRUNCATE on the real Postgres engine does not touch their
    in-memory databases.
    """
    import sqlalchemy
    from app.core.database import engine
    from sqlmodel import SQLModel

    table_names = list(SQLModel.metadata.tables.keys())
    if table_names:
        with engine.connect() as conn:
            stmt = f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"
            conn.execute(sqlalchemy.text(stmt))
            conn.commit()

    _seed_admin_impl()

    yield


# ── Valkey fakes (autouse) ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_async_valkey():
    """Patch the async Valkey singleton so unit tests need no live broker.

    The FastAPI lifespan (which calls init_async_valkey) never runs under
    ASGITransport, so without this patch get_async_valkey_client() raises
    RuntimeError. Tests that need specific async Valkey behavior inject
    into the yielded mock directly.
    """
    import app.core.valkey as _valkey_mod

    mock = AsyncMock()
    mock.incr.return_value = 1
    mock.expire.return_value = True
    mock.exists.return_value = 0
    mock.aclose.return_value = None

    original = _valkey_mod._async_client
    _valkey_mod._async_client = mock
    yield mock
    _valkey_mod._async_client = original


@pytest.fixture(autouse=True)
def _patch_sync_valkey():
    """Patch the sync Valkey singleton — symmetric to _patch_async_valkey.

    Consumer/stream unit tests that call get_valkey_client() directly (outside
    FastAPI dependency injection) need this so they never require a live broker.
    Tests that set dependency_overrides[get_valkey_client] use their own mock
    through FastAPI; this fake acts as a safe fallback for all other paths.
    """
    import app.core.valkey as _valkey_mod

    mock = MagicMock()
    mock.incr.return_value = 1
    mock.expire.return_value = True
    mock.exists.return_value = 0
    mock.setex.return_value = True
    mock.xadd.return_value = "1-0"
    mock.xack.return_value = 1
    mock.close.return_value = None

    original = _valkey_mod._client
    _valkey_mod._client = mock
    yield mock
    _valkey_mod._client = original


# ── Real Valkey opt-in (integration transport tests) ─────────────────────────

@pytest.fixture
def real_valkey():
    """Opt-in fixture for integration tests that require a live Valkey.

    Temporarily replaces the autouse fake with a real client at localhost:6379
    (Streams contract checks). Restore the fake on teardown.

    Usage:
        def test_stream_contract(real_valkey):
            real_valkey.xadd("stream", {"key": "val"})
    """
    import app.core.valkey as _valkey_mod

    _valkey_mod.init_valkey(os.environ["VALKEY_URL"])
    try:
        yield _valkey_mod.get_valkey_client()
    finally:
        _valkey_mod.close_valkey()


# ── Forced password-change fixtures (task 3.2 / 3.3) ────────────────────────

# Policy-compliant password for the forced-change flow (≥12 chars, upper, lower, digit).
_FORCED_CHANGE_NEW_PASSWORD = "TestAdminNew1A!"


@pytest.fixture
async def first_login_token(_db_isolation):
    """Raw first-login admin token (scope=password_change_only).

    The seeded admin has must_change_password=True, so the access token
    carries scope='password_change_only'. Use this fixture to assert that
    the 403 password_change_required gate blocks normal protected endpoints.
    """
    from app.core.valkey import get_valkey_client
    from app.main import app

    mock_valkey = MagicMock()
    mock_valkey.incr.return_value = 1
    mock_valkey.expire.return_value = True
    mock_valkey.exists.return_value = 0

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.post(
                "/auth/login",
                json={
                    "username": os.environ["ADMIN_USERNAME"],
                    "password": os.environ["ADMIN_PASSWORD"],
                },
            )
            assert resp.status_code == 200, f"Login failed: {resp.text}"
            token = resp.json()["access_token"]
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)

    return token


@pytest.fixture
async def authenticated_client(_db_isolation):
    """AsyncClient with a fully-scoped admin token (forced change completed).

    Executes the forced password-change flow during fixture setup:
      1. Login → password_change_only-scoped token
      2. POST /users/change-password with a policy-compliant password
      3. Re-login → full-access token

    Yields (client, full_token). The DB is already clean (from _db_isolation)
    when this fixture runs — it is safe to depend on _db_isolation explicitly
    to guarantee ordering.
    """
    from app.core.valkey import get_valkey_client
    from app.main import app

    mock_valkey = MagicMock()
    mock_valkey.incr.return_value = 1
    mock_valkey.expire.return_value = True
    mock_valkey.exists.return_value = 0
    mock_valkey.setex.return_value = True
    mock_valkey.close.return_value = None

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            # Step 1: first login → password_change_only token
            login_resp = await ac.post(
                "/auth/login",
                json={
                    "username": os.environ["ADMIN_USERNAME"],
                    "password": os.environ["ADMIN_PASSWORD"],
                },
            )
            assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
            pco_token = login_resp.json()["access_token"]

            # Step 2: change password using the restricted token
            change_resp = await ac.post(
                "/users/change-password",
                json={"new_password": _FORCED_CHANGE_NEW_PASSWORD},
                headers={"Authorization": f"Bearer {pco_token}"},
            )
            assert change_resp.status_code == 200, (
                f"Password change failed: {change_resp.text}"
            )

            # Step 3: re-login with the new password → full-access token
            relogin_resp = await ac.post(
                "/auth/login",
                json={
                    "username": os.environ["ADMIN_USERNAME"],
                    "password": _FORCED_CHANGE_NEW_PASSWORD,
                },
            )
            assert relogin_resp.status_code == 200, (
                f"Re-login failed: {relogin_resp.text}"
            )
            full_token = relogin_resp.json()["access_token"]

            yield ac, full_token
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)


@pytest.fixture
async def admin_token(authenticated_client) -> str:
    """Convenience fixture: just the fully-scoped admin access token."""
    _, token = authenticated_client
    return token


# ── Generic HTTP client ───────────────────────────────────────────────────────

@pytest.fixture
async def client():
    """AsyncClient mounted on the app in-memory via ASGITransport.

    The lifespan does NOT run under ASGITransport (no create_all, no
    seed_admin from the app side). Schema and seeding are owned by the
    session-scoped _create_schema and the function-scoped _db_isolation
    fixtures above.

    The autouse _patch_async_valkey and _patch_sync_valkey ensure
    get_async_valkey_client() / get_valkey_client() return mocks, so no
    live Valkey broker is required.
    """
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
