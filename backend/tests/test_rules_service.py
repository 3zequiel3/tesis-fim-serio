"""
Tests de la capa de servicio de reglas (Change 12).

Cubre: increment_ruleset_version, validate_pattern, publish_rule_sync,
create/update/delete (audit + counter), list_rules (orden RN-09).

Usa SQLite in-memory. Salta si psycopg no está disponible (Windows sin PostgreSQL).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.streams import verify_payload
from app.modules.agents.models import Agent, AgentStatus
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.rules.models import PublishedCommand, Rule, RuleAction, RuleSeverity, RulesetVersion
from app.modules.rules.service import (
    SEVERITY_ORDER,
    create_rule,
    delete_rule,
    increment_ruleset_version,
    list_rules,
    publish_rule_sync,
    update_rule,
    validate_pattern,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(mem_engine):
    with Session(mem_engine) as s:
        yield s


@pytest.fixture()
def admin_user(session) -> User:
    user = User(
        id=1,
        username="admin",
        email="admin@fim.local",
        password_hash="hashed",
        role="admin",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def mock_valkey() -> MagicMock:
    client = MagicMock()
    client.xadd = MagicMock()
    return client


@pytest.fixture()
def agent_with_secret(session) -> tuple[Agent, bytes]:
    secret = os.urandom(32)
    agent = Agent(
        agent_id="agent-001",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, secret


# ── validate_pattern ──────────────────────────────────────────────────────────


class TestValidatePattern:
    def test_valid_glob_star(self):
        validate_pattern("/etc/*")  # no lanza

    def test_valid_glob_question(self):
        validate_pattern("/var/log/?.log")  # no lanza

    def test_valid_literal_path(self):
        validate_pattern("/etc/passwd")  # no lanza

    def test_valid_bracket(self):
        validate_pattern("/proc/[0-9]*")  # no lanza

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_pattern("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_pattern("   ")


# ── increment_ruleset_version ─────────────────────────────────────────────────


class TestIncrementRulesetVersion:
    def test_creates_version_on_first_call(self, session):
        v = increment_ruleset_version(session)
        assert v == 1

    def test_increments_monotonically(self, session):
        v1 = increment_ruleset_version(session)
        v2 = increment_ruleset_version(session)
        v3 = increment_ruleset_version(session)
        assert v1 == 1
        assert v2 == 2
        assert v3 == 3

    def test_existing_row_is_reused(self, session):
        """Solo debe haber una fila en ruleset_versions."""
        increment_ruleset_version(session)
        increment_ruleset_version(session)
        rows = session.exec(select(RulesetVersion)).all()
        assert len(rows) == 1
        assert rows[0].version == 2

    def test_returns_new_value_not_old(self, session):
        """El valor retornado es el valor post-incremento."""
        v = increment_ruleset_version(session)
        assert v >= 1


# ── publish_rule_sync ─────────────────────────────────────────────────────────


class TestPublishRuleSync:
    def test_no_agents_returns_zero(self, session, mock_valkey):
        """Sin agentes registrados con secret no se publica nada."""
        count = publish_rule_sync(session, mock_valkey, new_version=1)
        assert count == 0
        mock_valkey.xadd.assert_not_called()
        rows = session.exec(select(PublishedCommand)).all()
        assert len(rows) == 0

    def test_one_agent_publishes_one_message(self, session, mock_valkey, agent_with_secret):
        agent, secret = agent_with_secret
        count = publish_rule_sync(session, mock_valkey, new_version=5)
        assert count == 1
        mock_valkey.xadd.assert_called_once()

    def test_signature_is_verifiable(self, session, mock_valkey, agent_with_secret):
        """El payload publicado lleva firma válida verificable con verify_payload."""
        import json

        agent, secret = agent_with_secret
        publish_rule_sync(session, mock_valkey, new_version=7)

        call_args = mock_valkey.xadd.call_args
        stream_name = call_args[0][0]
        msg_dict = call_args[0][1]
        assert stream_name == "commands"
        payload = json.loads(msg_dict["data"])
        assert verify_payload(secret, payload)

    def test_target_agent_id_is_correct(self, session, mock_valkey, agent_with_secret):
        """El payload lleva target_agent_id del agente correcto."""
        import json

        agent, secret = agent_with_secret
        publish_rule_sync(session, mock_valkey, new_version=3)

        call_args = mock_valkey.xadd.call_args
        payload = json.loads(call_args[0][1]["data"])
        assert payload["target_agent_id"] == agent.agent_id

    def test_inserts_published_command_row(self, session, mock_valkey, agent_with_secret):
        agent, _ = agent_with_secret
        publish_rule_sync(session, mock_valkey, new_version=4)
        rows = session.exec(select(PublishedCommand)).all()
        assert len(rows) == 1
        assert rows[0].command_type == "rule_sync"
        assert rows[0].target_agent_id == agent.agent_id
        assert rows[0].ruleset_version == 4

    def test_two_agents_two_messages(self, session, mock_valkey):
        """Con dos agentes se publican dos mensajes y dos rows en published_commands."""
        s2 = os.urandom(32)
        agent2 = Agent(agent_id="agent-002", status=AgentStatus.online, shared_secret_hex=s2.hex())
        s1 = os.urandom(32)
        agent1 = Agent(agent_id="agent-001", status=AgentStatus.online, shared_secret_hex=s1.hex())
        session.add(agent1)
        session.add(agent2)
        session.commit()

        count = publish_rule_sync(session, mock_valkey, new_version=10)
        assert count == 2
        assert mock_valkey.xadd.call_count == 2
        rows = session.exec(select(PublishedCommand)).all()
        assert len(rows) == 2

    def test_agent_without_secret_is_skipped(self, session, mock_valkey):
        """Agente sin shared_secret_hex no recibe mensaje."""
        agent = Agent(agent_id="agent-nosec", status=AgentStatus.offline, shared_secret_hex=None)
        session.add(agent)
        session.commit()
        count = publish_rule_sync(session, mock_valkey, new_version=1)
        assert count == 0
        mock_valkey.xadd.assert_not_called()

    def test_rules_included_in_payload(self, session, mock_valkey, agent_with_secret):
        """El payload incluye campo 'rules' con las reglas actuales."""
        import json

        agent, secret = agent_with_secret
        rule = Rule(
            pattern="/etc/*",
            severity=RuleSeverity.critical,
            action=RuleAction.auto_restore,
        )
        session.add(rule)
        session.commit()

        publish_rule_sync(session, mock_valkey, new_version=2)
        call_args = mock_valkey.xadd.call_args
        payload = json.loads(call_args[0][1]["data"])
        assert "rules" in payload
        assert isinstance(payload["rules"], list)
        assert len(payload["rules"]) == 1
        assert payload["rules"][0]["pattern"] == "/etc/*"


# ── create / update / delete — audit + counter ────────────────────────────────


class TestWriteOperations:
    def test_create_rule_writes_audit_log(self, session, mock_valkey, admin_user):
        create_rule(
            session,
            mock_valkey,
            admin_user.id,
            {"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
        )
        logs = session.exec(select(AuditLog)).all()
        assert len(logs) == 1
        assert logs[0].action == "rule_created"
        assert logs[0].target_type == "rule"

    def test_create_rule_increments_counter(self, session, mock_valkey, admin_user):
        create_rule(
            session,
            mock_valkey,
            admin_user.id,
            {"pattern": "/var/*", "severity": "high", "action": "alert_only"},
        )
        rv = session.exec(select(RulesetVersion)).first()
        assert rv is not None
        assert rv.version == 1

    def test_update_rule_writes_audit_log(self, session, mock_valkey, admin_user):
        rule = Rule(pattern="/etc/*", severity=RuleSeverity.high, action=RuleAction.alert_only)
        session.add(rule)
        session.commit()
        session.refresh(rule)

        update_rule(
            session,
            mock_valkey,
            admin_user.id,
            rule.id,
            {"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
        )
        logs = session.exec(select(AuditLog)).all()
        assert any(l.action == "rule_updated" for l in logs)

    def test_update_rule_persists_the_new_field_values(self, session, mock_valkey, admin_user):
        """
        US-16 (anexo §7, nivel 1 #5): el núcleo de la historia es que los campos
        cambien en la fila persistida, no que se escriba una auditoría. Se relee
        la fila desde la base en una sesión limpia para no leer el objeto en
        memoria que `update_rule` ya mutó.
        """
        rule = Rule(pattern="/etc/*", severity=RuleSeverity.low, action=RuleAction.alert_only)
        session.add(rule)
        session.commit()
        session.refresh(rule)
        rule_id = rule.id
        original_updated_at = rule.updated_at

        update_rule(
            session,
            mock_valkey,
            admin_user.id,
            rule_id,
            {"pattern": "/etc/ssh/*", "severity": "critical", "action": "auto_restore"},
        )

        session.expire_all()
        persisted = session.exec(select(Rule).where(Rule.id == rule_id)).one()
        assert persisted.pattern == "/etc/ssh/*"
        assert persisted.severity == RuleSeverity.critical
        assert persisted.action == RuleAction.auto_restore
        assert persisted.updated_at >= original_updated_at
        # No se creó una regla nueva: sigue habiendo una sola fila.
        assert len(session.exec(select(Rule)).all()) == 1

    def test_update_rule_partial_payload_keeps_untouched_fields(
        self, session, mock_valkey, admin_user
    ):
        """Los campos ausentes del payload conservan su valor previo."""
        rule = Rule(pattern="/var/log/*", severity=RuleSeverity.high, action=RuleAction.quarantine)
        session.add(rule)
        session.commit()
        session.refresh(rule)
        rule_id = rule.id

        update_rule(session, mock_valkey, admin_user.id, rule_id, {"severity": "medium"})

        session.expire_all()
        persisted = session.exec(select(Rule).where(Rule.id == rule_id)).one()
        assert persisted.severity == RuleSeverity.medium
        assert persisted.pattern == "/var/log/*"
        assert persisted.action == RuleAction.quarantine

    def test_delete_rule_removes_the_row(self, session, mock_valkey, admin_user):
        """
        US-17 (anexo §7, nivel 1 #5): la fila desaparece de la tabla. Hoy los
        tests de borrado sólo verifican la auditoría y el contador de versión.
        """
        kept = Rule(pattern="/keep/*", severity=RuleSeverity.low, action=RuleAction.alert_only)
        doomed = Rule(pattern="/tmp/*", severity=RuleSeverity.low, action=RuleAction.alert_only)
        session.add(kept)
        session.add(doomed)
        session.commit()
        session.refresh(kept)
        session.refresh(doomed)
        doomed_id = doomed.id
        kept_id = kept.id

        delete_rule(session, mock_valkey, admin_user.id, doomed_id)

        session.expire_all()
        assert session.exec(select(Rule).where(Rule.id == doomed_id)).first() is None
        # Sólo se borró la regla pedida.
        remaining = session.exec(select(Rule)).all()
        assert [r.id for r in remaining] == [kept_id]

    def test_update_rule_increments_counter(self, session, mock_valkey, admin_user):
        rule = Rule(pattern="/proc/*", severity=RuleSeverity.low, action=RuleAction.alert_only)
        session.add(rule)
        session.commit()
        session.refresh(rule)

        update_rule(
            session,
            mock_valkey,
            admin_user.id,
            rule.id,
            {"pattern": "/proc/*", "severity": "medium", "action": "manual_review"},
        )
        rv = session.exec(select(RulesetVersion)).first()
        assert rv is not None
        assert rv.version == 1

    def test_delete_rule_writes_audit_log(self, session, mock_valkey, admin_user):
        rule = Rule(pattern="/tmp/*", severity=RuleSeverity.low, action=RuleAction.alert_only)
        session.add(rule)
        session.commit()
        session.refresh(rule)

        delete_rule(session, mock_valkey, admin_user.id, rule.id)
        logs = session.exec(select(AuditLog)).all()
        assert any(l.action == "rule_deleted" for l in logs)

    def test_delete_rule_increments_counter(self, session, mock_valkey, admin_user):
        rule = Rule(pattern="/home/*", severity=RuleSeverity.medium, action=RuleAction.quarantine)
        session.add(rule)
        session.commit()
        session.refresh(rule)

        delete_rule(session, mock_valkey, admin_user.id, rule.id)
        rv = session.exec(select(RulesetVersion)).first()
        assert rv is not None
        assert rv.version == 1

    def test_multiple_writes_increment_counter_each_time(self, session, mock_valkey, admin_user):
        create_rule(
            session, mock_valkey, admin_user.id,
            {"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
        )
        create_rule(
            session, mock_valkey, admin_user.id,
            {"pattern": "/var/*", "severity": "high", "action": "alert_only"},
        )
        rv = session.exec(select(RulesetVersion)).first()
        assert rv is not None
        assert rv.version == 2

    def test_audit_log_target_type_is_rule(self, session, mock_valkey, admin_user):
        create_rule(
            session, mock_valkey, admin_user.id,
            {"pattern": "/usr/*", "severity": "low", "action": "alert_only"},
        )
        logs = session.exec(select(AuditLog)).all()
        assert all(l.target_type == "rule" for l in logs)


# ── list_rules — orden severity ───────────────────────────────────────────────


class TestListRules:
    def test_empty_returns_empty_list(self, session):
        assert list_rules(session) == []

    def test_order_critical_before_high_before_medium_before_low(self, session):
        for sev, pat in [
            (RuleSeverity.low, "/low/*"),
            (RuleSeverity.medium, "/med/*"),
            (RuleSeverity.critical, "/crit/*"),
            (RuleSeverity.high, "/high/*"),
        ]:
            session.add(Rule(pattern=pat, severity=sev, action=RuleAction.alert_only))
        session.commit()

        rules = list_rules(session)
        severities = [r.severity.value for r in rules]
        assert severities == ["critical", "high", "medium", "low"]

    def test_same_severity_ordered_by_id(self, session):
        for pat in ["/b/*", "/a/*", "/c/*"]:
            session.add(Rule(pattern=pat, severity=RuleSeverity.high, action=RuleAction.alert_only))
        session.commit()

        rules = list_rules(session)
        ids = [r.id for r in rules]
        assert ids == sorted(ids)

    def test_severity_order_constant_values(self):
        assert SEVERITY_ORDER["critical"] == 0
        assert SEVERITY_ORDER["high"] == 1
        assert SEVERITY_ORDER["medium"] == 2
        assert SEVERITY_ORDER["low"] == 3
