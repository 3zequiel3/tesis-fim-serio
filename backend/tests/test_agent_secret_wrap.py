"""
Agent shared secret wrapped at rest (D86/RN-180, Change 68).

Covers the helper (`app.modules.agents.secret_wrap`), the six read sites with both storage
formats (wrapped `v1:` and legacy plain hex), the data migration, the lifespan key checks and
the `certs-init` key generation. The session key is loaded by `conftest.py`.
"""

from __future__ import annotations

import json
import os
import stat
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import sqlalchemy
import structlog
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.streams import sign_payload, verify_payload
from app.modules.agents import secret_wrap
from app.modules.agents.models import Agent, AgentStatus
from app.modules.agents.secret_wrap import (
    AgentSecretUnwrapError,
    ensure_wrap_key_file,
    load_wrap_key,
    unwrap_agent_secret,
    wrap_agent_secret,
    wrap_legacy_agent_secrets,
)
from app.modules.rules.models import PublishedCommand

from tests.conftest import WRAP_KEY_PATH


# ── helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_module_logger(monkeypatch):
    """structlog caches the module logger on first use, which would bypass `capture_logs()`."""
    monkeypatch.setattr(secret_wrap, "log", structlog.get_logger())


@pytest.fixture()
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _write_key(path, size: int = 32, mode: int = 0o600) -> str:
    path.write_bytes(os.urandom(size))
    os.chmod(path, mode)
    return str(path)


@pytest.fixture()
def restore_loaded_key():
    """Tests that call `load_wrap_key` with other keys must leave the session key loaded."""
    yield
    load_wrap_key(WRAP_KEY_PATH)


# ── 7.2 helper ───────────────────────────────────────────────────────────────


def test_round_trip() -> None:
    secret = os.urandom(32)
    stored = wrap_agent_secret("agent-a", secret)
    assert stored.startswith("v1:")
    assert unwrap_agent_secret("agent-a", stored) == secret


def test_two_wraps_of_the_same_secret_differ_and_both_unwrap() -> None:
    secret = os.urandom(32)
    first = wrap_agent_secret("agent-a", secret)
    second = wrap_agent_secret("agent-a", secret)
    assert first != second
    assert unwrap_agent_secret("agent-a", first) == unwrap_agent_secret("agent-a", second) == secret


def test_different_aad_fails() -> None:
    stored = wrap_agent_secret("agent-a", os.urandom(32))
    with pytest.raises(AgentSecretUnwrapError):
        unwrap_agent_secret("agent-b", stored)


def test_tampered_payload_fails() -> None:
    stored = wrap_agent_secret("agent-a", os.urandom(32))
    index = len("v1:") + 20
    flipped = "A" if stored[index] != "A" else "B"
    with pytest.raises(AgentSecretUnwrapError):
        unwrap_agent_secret("agent-a", stored[:index] + flipped + stored[index + 1:])


def test_truncated_and_non_base64_payloads_fail() -> None:
    for stored in ("v1:", "v1:AAAA", "v1:!!!not-base64!!!"):
        with pytest.raises(AgentSecretUnwrapError):
            unwrap_agent_secret("agent-a", stored)


def test_unknown_version_prefix_fails_closed() -> None:
    stored = wrap_agent_secret("agent-a", os.urandom(32))
    with pytest.raises(AgentSecretUnwrapError):
        unwrap_agent_secret("agent-a", "v2:" + stored[len("v1:"):])


def test_legacy_hex_is_still_readable() -> None:
    secret = os.urandom(32)
    assert unwrap_agent_secret("agent-a", secret.hex()) == secret
    assert len(secret.hex()) == 64


def test_invalid_legacy_hex_fails() -> None:
    with pytest.raises(AgentSecretUnwrapError):
        unwrap_agent_secret("agent-a", "zz" * 32)


def test_unwrap_error_is_a_value_error_and_hides_the_stored_value() -> None:
    assert issubclass(AgentSecretUnwrapError, ValueError)
    stored = wrap_agent_secret("agent-a", os.urandom(32))
    for bad_value, agent_id in ((stored, "agent-b"), ("zz" * 32, "agent-a"), ("v2:" + stored, "agent-a")):
        with pytest.raises(AgentSecretUnwrapError) as excinfo:
            unwrap_agent_secret(agent_id, bad_value)
        assert bad_value not in str(excinfo.value)
        assert bad_value[len("v1:"):] not in str(excinfo.value)


def test_wrap_rejects_a_secret_of_the_wrong_length() -> None:
    with pytest.raises(ValueError):
        wrap_agent_secret("agent-a", os.urandom(16))


def test_helper_without_a_loaded_key_raises_runtime_error(monkeypatch) -> None:
    monkeypatch.setattr(secret_wrap, "_wrap_key", None)
    with pytest.raises(RuntimeError) as excinfo:
        wrap_agent_secret("agent-a", os.urandom(32))
    assert not isinstance(excinfo.value, ValueError)
    stored = "v1:" + "A" * 80
    with pytest.raises(RuntimeError) as excinfo:
        unwrap_agent_secret("agent-a", stored)
    assert not isinstance(excinfo.value, ValueError)
    # The legacy hex path needs no key.
    assert unwrap_agent_secret("agent-a", "00" * 32) == bytes(32)


# ── 7.4 the six read sites, both storage formats ─────────────────────────────


def _store(secret: bytes, agent_id: str, wrapped: bool) -> str:
    return wrap_agent_secret(agent_id, secret) if wrapped else secret.hex()


@pytest.fixture(params=["legacy_hex", "wrapped"])
def stored_agent(request, mem_engine):
    secret = os.urandom(32)
    agent = Agent(
        agent_id="site-agent",
        status=AgentStatus.offline,
        shared_secret_hex=_store(secret, "site-agent", request.param == "wrapped"),
    )
    with Session(mem_engine) as session:
        session.add(agent)
        session.commit()
    return secret, mem_engine


def test_events_consumer_site_verifies(stored_agent) -> None:
    import app.modules.events.consumer as events_consumer

    secret, engine = stored_agent
    with patch.object(events_consumer, "engine", engine):
        auth = events_consumer._get_agent_auth("site-agent")
    assert auth.shared_secret == secret
    payload = {"agent_id": "site-agent", "n": 1}
    payload["signature"] = sign_payload(secret, payload)
    assert verify_payload(auth.shared_secret, payload)


def test_heartbeat_site_verifies(stored_agent) -> None:
    import app.modules.agents.heartbeat_consumer as hc

    secret, engine = stored_agent
    payload = {
        "agent_id": "site-agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_pressure": 0.1,
        "ruleset_version": 0,
        "shutdown": False,
        "schema_version": 1,
        "queue_size": 0,
    }
    payload["signature"] = sign_payload(secret, payload)
    with patch.object(hc, "engine", engine):
        hc._handle_heartbeat({"data": json.dumps(payload)})
    with Session(engine) as session:
        assert session.get(Agent, "site-agent").status == AgentStatus.online


def test_command_ack_site_reads_the_secret(stored_agent) -> None:
    from app.modules.agents.command_ack_consumer import _get_shared_secret

    secret, engine = stored_agent
    with Session(engine) as session:
        assert _get_shared_secret(session, "site-agent") == secret


def test_agents_streams_site_reads_the_secret(stored_agent) -> None:
    from app.modules.agents.streams import _get_agent_secret

    secret, engine = stored_agent
    with Session(engine) as session:
        agent = session.get(Agent, "site-agent")
        assert _get_agent_secret(agent) == secret


def test_actions_streams_site_reads_the_secret(stored_agent) -> None:
    from app.modules.actions.streams import _get_agent_secret

    secret, engine = stored_agent
    with Session(engine) as session:
        assert _get_agent_secret(session, "site-agent") == secret


def test_rule_sync_is_signed_with_the_secret(stored_agent) -> None:
    from app.modules.rules.service import enqueue_rule_sync

    secret, engine = stored_agent
    with Session(engine) as session:
        assert enqueue_rule_sync(session, 7) == 1
        session.commit()
        command = session.exec(select(PublishedCommand)).one()
    assert verify_payload(secret, json.loads(command.payload))


# ── unwrap failures keep each site's error semantics (D37/RN-131) ────────────


@pytest.fixture()
def corrupt_agent(mem_engine):
    stored = wrap_agent_secret("other-agent", os.urandom(32))  # AAD mismatch -> cannot unwrap
    with Session(mem_engine) as session:
        session.add(Agent(agent_id="site-agent", status=AgentStatus.offline, shared_secret_hex=stored))
        session.commit()
    return mem_engine


def test_sites_that_capture_keep_capturing(corrupt_agent) -> None:
    import app.modules.agents.heartbeat_consumer as hc
    import app.modules.events.consumer as events_consumer
    from app.modules.agents.command_ack_consumer import _get_shared_secret

    with patch.object(events_consumer, "engine", corrupt_agent):
        assert events_consumer._get_agent_auth("site-agent").shared_secret is None
    with Session(corrupt_agent) as session:
        assert _get_shared_secret(session, "site-agent") is None

    payload = {
        "agent_id": "site-agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_pressure": 0.1,
        "ruleset_version": 0,
        "shutdown": False,
        "schema_version": 1,
        "signature": "00",
    }
    with patch.object(hc, "engine", corrupt_agent):
        hc._handle_heartbeat({"data": json.dumps(payload)})
    with Session(corrupt_agent) as session:
        assert session.get(Agent, "site-agent").status == AgentStatus.offline


def test_sites_that_propagate_keep_propagating(corrupt_agent) -> None:
    from app.modules.actions.streams import _get_agent_secret as actions_secret
    from app.modules.agents.streams import _get_agent_secret as agents_secret
    from app.modules.rules.service import enqueue_rule_sync

    with Session(corrupt_agent) as session:
        agent = session.get(Agent, "site-agent")
        with pytest.raises(ValueError):
            agents_secret(agent)
        with pytest.raises(ValueError):
            actions_secret(session, "site-agent")
        with pytest.raises(ValueError):
            enqueue_rule_sync(session, 1)


def test_only_the_helper_applies_fromhex_to_the_secret_column() -> None:
    """Spec scenario «Los seis sitios usan el helper»."""
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(path.relative_to(app_dir))
        for path in app_dir.rglob("*.py")
        if path.name != "secret_wrap.py"
        and re.search(r"fromhex\([^)]*shared_secret_hex", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# ── 7.5 data migration ───────────────────────────────────────────────────────


def test_migration_wraps_legacy_rows_and_is_idempotent(mem_engine) -> None:
    secrets_by_id = {f"legacy-{i}": os.urandom(32) for i in range(3)}
    with Session(mem_engine) as session:
        for agent_id, secret in secrets_by_id.items():
            session.add(Agent(agent_id=agent_id, status=AgentStatus.offline, shared_secret_hex=secret.hex()))
        session.add(Agent(agent_id="no-secret", status=AgentStatus.offline, shared_secret_hex=None))
        session.add(Agent(agent_id="bad-hex", status=AgentStatus.offline, shared_secret_hex="not-hex-at-all"))
        session.commit()

    with structlog.testing.capture_logs() as captured, Session(mem_engine) as session:
        assert wrap_legacy_agent_secrets(session) == 3

    with Session(mem_engine) as session:
        for agent_id, secret in secrets_by_id.items():
            stored = session.get(Agent, agent_id).shared_secret_hex
            assert stored.startswith("v1:")
            assert unwrap_agent_secret(agent_id, stored) == secret
        assert session.get(Agent, "no-secret").shared_secret_hex is None
        assert session.get(Agent, "bad-hex").shared_secret_hex == "not-hex-at-all"
        before = {a.agent_id: a.shared_secret_hex for a in session.exec(select(Agent)).all()}

    invalid = [e for e in captured if e["event"] == "agents.secret_wrap.legacy_invalid"]
    assert [e["agent_id"] for e in invalid] == ["bad-hex"]
    assert invalid[0]["log_level"] == "error"
    summary = [e for e in captured if e["event"] == "agents.secret_wrap.migrated"]
    assert summary[0]["wrapped"] == 3 and summary[0]["skipped_invalid"] == 1
    for event in captured:
        assert all("not-hex-at-all" not in str(value) for value in event.values())

    with Session(mem_engine) as session:
        assert wrap_legacy_agent_secrets(session) == 0
        after = {a.agent_id: a.shared_secret_hex for a in session.exec(select(Agent)).all()}
    assert after == before


# ── 7.7 / 7.8 / 7.9 key loading and lifespan ────────────────────────────────


def _reasons(captured) -> list[str]:
    return [e["reason"] for e in captured if e["event"] == "backend.agent_secret_wrap_key.invalid"]


def test_load_wrap_key_causes(tmp_path, restore_loaded_key) -> None:
    cases = {
        "": "not_configured",
        str(tmp_path / "absent.key"): "missing",
        _write_key(tmp_path / "short.key", 31): "invalid_length",
        _write_key(tmp_path / "long.key", 33): "invalid_length",
        _write_key(tmp_path / "empty.key", 0): "invalid_length",
        _write_key(tmp_path / "g640.key", 32, 0o640): "permissive_mode",
        _write_key(tmp_path / "g644.key", 32, 0o644): "permissive_mode",
        _write_key(tmp_path / "exec.key", 32, 0o700): "permissive_mode",
        str(tmp_path): "unreadable",
    }
    for path, reason in cases.items():
        with structlog.testing.capture_logs() as captured:
            with pytest.raises(RuntimeError) as excinfo:
                load_wrap_key(path)
        assert _reasons(captured) == [reason], path
        assert reason in str(excinfo.value)


def test_load_wrap_key_accepts_0400_and_0600(tmp_path, restore_loaded_key) -> None:
    for mode in (0o400, 0o600):
        path = _write_key(tmp_path / f"ok{mode:o}.key", 32, mode)
        load_wrap_key(path)


def test_failed_load_keeps_the_previous_key(tmp_path, restore_loaded_key) -> None:
    stored = wrap_agent_secret("agent-a", bytes(32))
    with pytest.raises(RuntimeError):
        load_wrap_key(str(tmp_path / "absent.key"))
    assert unwrap_agent_secret("agent-a", stored) == bytes(32)


@pytest.fixture()
def lifespan_env(monkeypatch, restore_loaded_key):
    """Spies `create_all` and the order of the early lifespan steps; no database needed
    because the key check must abort before touching it."""
    import app.main as main_module

    # `main_module.settings`, not a fresh import: other tests reload `app.core.config`.
    settings = main_module.settings

    calls: list[str] = []
    monkeypatch.setattr(main_module, "check_schema_version", lambda engine: calls.append("schema"))
    monkeypatch.setattr(main_module, "init_valkey", lambda url: calls.append("init_valkey"))
    monkeypatch.setattr(main_module.SQLModel.metadata, "create_all", lambda engine: calls.append("create_all"))

    def _point(path: str) -> None:
        monkeypatch.setattr(settings, "agent_secret_wrap_key_path", path)

    return calls, _point


@pytest.mark.parametrize(
    "build, reason",
    [
        (lambda tmp: str(tmp / "absent.key"), "missing"),
        (lambda tmp: _write_key(tmp / "k31", 31), "invalid_length"),
        (lambda tmp: _write_key(tmp / "k0", 0), "invalid_length"),
        (lambda tmp: "", "not_configured"),
        (lambda tmp: _write_key(tmp / "k640", 32, 0o640), "permissive_mode"),
        (lambda tmp: _write_key(tmp / "k644", 32, 0o644), "permissive_mode"),
    ],
)
def test_lifespan_aborts_before_create_all_without_a_valid_key(
    lifespan_env, tmp_path, build, reason
) -> None:
    from fastapi.testclient import TestClient

    import app.main as main_module

    calls, point = lifespan_env
    point(build(tmp_path))
    with structlog.testing.capture_logs() as captured:
        with pytest.raises(RuntimeError):
            with TestClient(main_module.app):
                pass  # pragma: no cover - the lifespan must not complete
    assert "create_all" not in calls and "init_valkey" not in calls
    assert calls == ["schema"]  # the schema guard (change 66) runs first, the key right after
    assert _reasons(captured) == [reason]


def test_lifespan_loads_keys_with_0400_and_0600(lifespan_env, tmp_path, monkeypatch) -> None:
    import app.main as main_module

    calls, point = lifespan_env
    # Stop right after the key load: init_valkey is the next step.
    class _Stop(Exception):
        pass

    def _stop(url):
        raise _Stop

    monkeypatch.setattr(main_module, "init_valkey", _stop)
    from fastapi.testclient import TestClient

    for mode in (0o400, 0o600):
        point(_write_key(tmp_path / f"k{mode:o}", 32, mode))
        with pytest.raises(_Stop):
            with TestClient(main_module.app):
                pass  # pragma: no cover


def test_importing_config_does_not_require_the_key_file(tmp_path) -> None:
    """certs-init imports `app.core.config` before the key exists (D-3)."""
    import subprocess
    import sys

    env = {
        k: v
        for k, v in os.environ.items()
        if k != "AGENT_SECRET_WRAP_KEY_PATH"
    }
    env["AGENT_SECRET_WRAP_KEY_PATH"] = str(tmp_path / "does-not-exist.key")
    result = subprocess.run(
        [sys.executable, "-c", "import app.core.config as c; print(c.settings.agent_secret_wrap_key_path)"],
        env=env,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.returncode == 0, result.stderr
    assert not os.path.exists(tmp_path / "does-not-exist.key")


# ── 7.10 ensure_wrap_key_file / certs-init ───────────────────────────────────


def test_ensure_wrap_key_file_creates_0400_32_bytes(tmp_path) -> None:
    path = tmp_path / "secrets" / "agent-secret-wrap.key"  # parent created when missing
    ensure_wrap_key_file(str(path))
    assert path.stat().st_size == 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    load_wrap_key(str(path))  # what certs-init writes is what the backend accepts
    load_wrap_key(WRAP_KEY_PATH)


def test_ensure_wrap_key_file_second_call_leaves_the_file_identical(tmp_path) -> None:
    path = tmp_path / "wrap.key"
    ensure_wrap_key_file(str(path))
    first = path.read_bytes()
    ensure_wrap_key_file(str(path))
    assert path.read_bytes() == first


def test_ensure_wrap_key_file_refuses_a_file_of_another_length(tmp_path) -> None:
    path = tmp_path / "wrap.key"
    path.write_bytes(b"short")
    with pytest.raises(RuntimeError):
        ensure_wrap_key_file(str(path))
    assert path.read_bytes() == b"short"


def test_certs_init_main_returns_1_when_the_key_step_fails(tmp_path, monkeypatch) -> None:
    from app.core import certs_init

    certs = tmp_path / "certs"
    certs.mkdir()
    bad_key = tmp_path / "wrap.key"
    bad_key.write_bytes(b"short")
    for name, filename in (
        ("CA_CERT_PATH", "ca.pem"),
        ("CA_KEY_PATH", "ca-key.pem"),
        ("BACKEND_CERT_PATH", "backend.pem"),
        ("BACKEND_KEY_PATH", "backend-key.pem"),
        ("BACKEND_VALKEY_CERT_PATH", "backend-valkey.pem"),
        ("BACKEND_VALKEY_KEY_PATH", "backend-valkey-key.pem"),
    ):
        monkeypatch.setenv(name, str(certs / filename))
    monkeypatch.setenv("VALKEY_TLS_DIR", str(tmp_path / "valkey_tls"))
    monkeypatch.setenv("CONSOLE_TLS_GENERATED_DIR", str(tmp_path / "console_tls"))
    monkeypatch.setenv("CONSOLE_TLS_MODE", "off")
    monkeypatch.setenv("AGENT_SECRET_WRAP_KEY_PATH", str(bad_key))
    assert certs_init.main() == 1
    assert bad_key.read_bytes() == b"short"


def test_certs_init_wrap_key_only_creates_the_key(tmp_path, monkeypatch) -> None:
    from app.core import certs_init

    path = tmp_path / "secrets" / "wrap.key"
    monkeypatch.setenv("AGENT_SECRET_WRAP_KEY_PATH", str(path))
    assert certs_init.main(["--wrap-key-only"]) == 0
    assert path.stat().st_size == 32
    assert certs_init.main(["--wrap-key-only"]) == 0  # idempotent


# ── 7.3 / 7.11 real Postgres: bootstrap persists the secret wrapped ──────────


def test_bootstrap_persists_the_secret_wrapped_in_postgres(tmp_path) -> None:
    """Full bootstrap against the test database; the column is read with raw SQL."""
    from argon2 import PasswordHasher

    from app.core.database import engine
    from app.core.pki import ensure_ca
    from app.modules.agents.service import bootstrap_agent
    from tests.test_bootstrap_tls_listener import _build_csr

    from app.modules.agents.models import AgentBootstrapRequest

    agent_id = f"wrapped-{uuid.uuid4().hex[:8]}"
    bootstrap_secret = "b" * 32
    ca_cert, ca_key = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    ensure_ca(str(ca_cert), str(ca_key))
    with Session(engine) as session:
        session.add(
            Agent(
                agent_id=agent_id,
                status=AgentStatus.offline,
                bootstrap_secret_hash=PasswordHasher().hash(bootstrap_secret),
            )
        )
        session.commit()
    try:
        with Session(engine) as session:
            response = bootstrap_agent(
                AgentBootstrapRequest(
                    agent_id=agent_id, csr_pem=_build_csr(agent_id), bootstrap_secret=bootstrap_secret
                ),
                session,
                str(ca_cert),
                str(ca_key),
            )
        with engine.connect() as conn:
            stored = conn.execute(
                sqlalchemy.text("SELECT shared_secret_hex FROM agents WHERE agent_id = :a"),
                {"a": agent_id},
            ).scalar_one()
        assert stored.startswith("v1:")
        assert response.shared_secret_hex not in stored
        assert unwrap_agent_secret(agent_id, stored) == bytes.fromhex(response.shared_secret_hex)
    finally:
        with Session(engine) as session:
            agent = session.get(Agent, agent_id)
            if agent is not None:
                session.delete(agent)
                session.commit()


def test_lifespan_wraps_legacy_secrets_before_the_consumers_start() -> None:
    """The real lifespan, on the test Postgres: a legacy row is wrapped by the first startup,
    and a second startup leaves it unchanged (idempotent)."""
    from fastapi.testclient import TestClient

    import app.main as main_module
    from app.core.database import engine

    secret = os.urandom(32)
    with Session(engine) as session:
        session.add(
            Agent(agent_id="lifespan-legacy", status=AgentStatus.offline, shared_secret_hex=secret.hex())
        )
        session.commit()

    def _stored() -> str:
        with engine.connect() as conn:
            return conn.execute(
                sqlalchemy.text("SELECT shared_secret_hex FROM agents WHERE agent_id = 'lifespan-legacy'")
            ).scalar_one()

    with TestClient(main_module.app):
        first = _stored()
    assert first.startswith("v1:")
    assert unwrap_agent_secret("lifespan-legacy", first) == secret

    with TestClient(main_module.app):
        assert _stored() == first
