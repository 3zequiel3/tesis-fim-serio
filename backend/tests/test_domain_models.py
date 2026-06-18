import pytest

from app.modules.agents.models import AgentStatus, BaselineStatus
from app.modules.alerts.models import AlertChannel, AlertSeverity
from app.modules.events.models import EventStatus, RejectionReason
from app.modules.rules.models import PublishedCommand, RuleAction, RuleSeverity


class TestEventStatus:
    def test_all_canonical_values(self):
        for v in ("pending", "approved", "rejected", "auto_restored",
                  "quarantined", "alert_only", "superseded"):
            assert EventStatus(v).value == v

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError):
            EventStatus("PENDING")

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            EventStatus("blocked")


class TestRejectionReason:
    def test_all_canonical_values(self):
        for v in ("clock_skew", "invalid_schema", "invalid_signature",
                  "unknown_agent", "duplicate_event", "rate_limited"):
            assert RejectionReason(v).value == v

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            RejectionReason("expired")


class TestRuleAction:
    def test_all_canonical_values(self):
        for v in ("auto_restore", "quarantine", "manual_review", "alert_only"):
            assert RuleAction(v).value == v

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            RuleAction("block")


class TestRuleSeverity:
    def test_all_canonical_values(self):
        for v in ("critical", "high", "medium", "low"):
            assert RuleSeverity(v).value == v


class TestAgentStatus:
    def test_all_canonical_values(self):
        for v in ("online", "offline", "draining", "dead"):
            assert AgentStatus(v).value == v

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            AgentStatus("idle")


class TestBaselineStatus:
    def test_canonical_values(self):
        assert BaselineStatus("present").value == "present"
        assert BaselineStatus("absent").value == "absent"

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            BaselineStatus("missing")


class TestAlertSeverity:
    def test_all_canonical_values(self):
        for v in ("critical", "high", "medium", "low"):
            assert AlertSeverity(v).value == v


class TestAlertChannel:
    def test_all_canonical_values(self):
        for v in ("n8n", "smtp_fallback", "webhook_fallback", "log_only"):
            assert AlertChannel(v).value == v

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            AlertChannel("email")


class TestPublishedCommand:
    def test_instantiation_with_required_fields(self):
        cmd = PublishedCommand(
            command_type="rule_sync",
            target_agent_id="agent-001",
            ruleset_version=5,
        )
        assert cmd.command_type == "rule_sync"
        assert cmd.target_agent_id == "agent-001"
        assert cmd.ruleset_version == 5
        assert cmd.id is None  # PK sin asignar hasta insert

    def test_target_agent_id_nullable(self):
        """target_agent_id admite None (D10 — check OR target_agent_id IS NULL)."""
        cmd = PublishedCommand(
            command_type="rule_sync",
            target_agent_id=None,
            ruleset_version=1,
        )
        assert cmd.target_agent_id is None

    def test_published_at_has_default(self):
        from datetime import datetime

        cmd = PublishedCommand(
            command_type="rule_sync",
            target_agent_id="agent-001",
            ruleset_version=3,
        )
        assert cmd.published_at is not None
        assert isinstance(cmd.published_at, datetime)
