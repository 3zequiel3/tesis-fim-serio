import pytest

from app.modules.agents.models import AgentStatus, BaselineStatus
from app.modules.alerts.models import AlertChannel, AlertSeverity
from app.modules.events.models import EventStatus, RejectionReason
from app.modules.rules.models import RuleAction, RuleSeverity


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
                  "unknown_agent", "duplicate_event"):
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
