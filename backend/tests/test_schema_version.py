"""
D84/RN-178 (Change 66) — schema version registry, tree sync and startup guard.

The tree test keeps `EXPECTED_SCHEMA_VERSION` in sync with `backend/db/migrations/`.
The guard tests run against an ephemeral database created on the test server, so they
never touch `fim_test`.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import pytest
import sqlalchemy
import structlog
from sqlalchemy.engine import make_url

from app.core.schema_version import (
    EXPECTED_SCHEMA_VERSION,
    SchemaVersionError,
    check_schema_version,
)

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"
NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
REGISTRY_FILE = MIGRATIONS_DIR / "000_schema_migrations.sql"


def _tree_versions() -> list[int]:
    return sorted(
        int(m.group(1))
        for p in MIGRATIONS_DIR.iterdir()
        if p.suffix == ".sql" and (m := NAME_RE.match(p.name))
    )


# ── Tree test ────────────────────────────────────────────────────────────────

def test_expected_version_matches_highest_migration_in_tree() -> None:
    highest = max(_tree_versions())
    assert EXPECTED_SCHEMA_VERSION == highest, (
        f"EXPECTED_SCHEMA_VERSION is {EXPECTED_SCHEMA_VERSION} but the highest migration in "
        f"backend/db/migrations/ is {highest:03d}: raise the constant in "
        "app/core/schema_version.py in the same commit that adds the migration"
    )


def test_migration_tree_is_contiguous_from_zero_without_duplicates() -> None:
    versions = _tree_versions()
    assert len(versions) == len(set(versions)), "duplicate migration numbers in the tree"
    assert versions == list(range(len(versions))), "migration numbering must be contiguous from 000"
    assert REGISTRY_FILE.is_file()


# ── Ephemeral database ───────────────────────────────────────────────────────

@pytest.fixture
def ephemeral_engine(monkeypatch):
    from app.core.config import settings

    base_url = make_url(str(settings.database_url))
    name = f"fim_schema_{uuid.uuid4().hex[:12]}"
    admin = sqlalchemy.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sqlalchemy.text(f'CREATE DATABASE "{name}"'))
    engine = sqlalchemy.create_engine(base_url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _register(engine, upto: int) -> None:
    """Create the registry and register versions 0..upto."""
    files = {int(p.name[:3]): p for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")}
    with engine.begin() as conn:
        conn.exec_driver_sql(REGISTRY_FILE.read_text(encoding="utf-8"))
        for version in range(upto + 1):
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO schema_migrations (version, filename, sha256) "
                    "VALUES (:v, :f, :s)"
                ),
                {
                    "v": version,
                    "f": files[version].name,
                    "s": hashlib.sha256(files[version].read_bytes()).hexdigest(),
                },
            )


def _outdated(captured: list[dict]) -> dict:
    events = [e for e in captured if e.get("event") == "backend.schema_outdated"]
    assert len(events) == 1, captured
    return events[0]


# ── check_schema_version ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_module_logger(monkeypatch):
    """structlog runs with cache_logger_on_first_use=True: a module-level logger bound by
    an earlier test would bypass `capture_logs()`. A fresh logger makes the log assertions
    independent of test order."""
    from app.core import schema_version

    monkeypatch.setattr(schema_version, "log", structlog.get_logger())


def test_check_without_registry_raises_with_null_found_version(ephemeral_engine) -> None:
    with structlog.testing.capture_logs() as captured:
        with pytest.raises(SchemaVersionError):
            check_schema_version(ephemeral_engine)
    event = _outdated(captured)
    assert event["log_level"] == "error"
    assert event["found_version"] is None
    assert event["expected_version"] == EXPECTED_SCHEMA_VERSION
    assert "migrar.py" in event["remedy"]


def test_check_with_registry_behind_raises(ephemeral_engine) -> None:
    _register(ephemeral_engine, EXPECTED_SCHEMA_VERSION - 1)
    with structlog.testing.capture_logs() as captured:
        with pytest.raises(SchemaVersionError):
            check_schema_version(ephemeral_engine)
    event = _outdated(captured)
    assert event["found_version"] == EXPECTED_SCHEMA_VERSION - 1
    assert event["expected_version"] == EXPECTED_SCHEMA_VERSION


def test_check_with_registry_up_to_date_returns_version(ephemeral_engine) -> None:
    _register(ephemeral_engine, EXPECTED_SCHEMA_VERSION)
    with structlog.testing.capture_logs() as captured:
        assert check_schema_version(ephemeral_engine) == EXPECTED_SCHEMA_VERSION
    ok = [e for e in captured if e.get("event") == "backend.schema_version"]
    assert len(ok) == 1 and ok[0]["log_level"] == "info"
    assert ok[0]["found_version"] == EXPECTED_SCHEMA_VERSION


def test_check_with_registry_ahead_does_not_abort(ephemeral_engine) -> None:
    _register(ephemeral_engine, EXPECTED_SCHEMA_VERSION)
    with ephemeral_engine.begin() as conn:
        conn.execute(
            sqlalchemy.text(
                "INSERT INTO schema_migrations (version, filename, sha256) "
                "VALUES (:v, 'future.sql', :s)"
            ),
            {"v": EXPECTED_SCHEMA_VERSION + 1, "s": "0" * 64},
        )
    assert check_schema_version(ephemeral_engine) == EXPECTED_SCHEMA_VERSION + 1


# ── Real lifespan ────────────────────────────────────────────────────────────

def _point_app_at(monkeypatch, engine) -> None:
    import app.main as main_module
    from app.modules.auth import service as auth_service

    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(auth_service, "engine", engine)


def test_startup_aborts_before_create_all_on_outdated_registry(
    ephemeral_engine, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    import app.main as main_module

    _register(ephemeral_engine, EXPECTED_SCHEMA_VERSION - 1)
    _point_app_at(monkeypatch, ephemeral_engine)

    with pytest.raises(SchemaVersionError):
        with TestClient(main_module.app):
            pass  # pragma: no cover - the lifespan must not complete

    # create_all did not run, seed_admin did not run.
    tables = set(sqlalchemy.inspect(ephemeral_engine).get_table_names())
    assert "agents" not in tables
    assert "users" not in tables


def test_startup_succeeds_on_up_to_date_registry(ephemeral_engine, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import app.main as main_module

    _register(ephemeral_engine, EXPECTED_SCHEMA_VERSION)
    _point_app_at(monkeypatch, ephemeral_engine)

    with TestClient(main_module.app):
        pass

    assert "agents" in set(sqlalchemy.inspect(ephemeral_engine).get_table_names())
    with ephemeral_engine.connect() as conn:
        assert conn.execute(sqlalchemy.text("SELECT count(*) FROM users")).scalar() == 1


# ── Harness ──────────────────────────────────────────────────────────────────

def test_harness_registers_versions_and_survives_truncate_isolation() -> None:
    """Writes rows through the isolation fixture's reach, then checks the registry.

    `_db_isolation` already TRUNCATEd before this test; the registry must be intact.
    """
    from app.core.database import engine

    with engine.connect() as conn:
        versions = [
            r[0]
            for r in conn.execute(
                sqlalchemy.text("SELECT version FROM schema_migrations ORDER BY version")
            )
        ]
    assert versions == list(range(EXPECTED_SCHEMA_VERSION + 1))
