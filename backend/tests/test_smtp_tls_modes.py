"""
C46 — SMTP transport security modes (D43/RN-137).

Before this change `send_smtp` passed `start_tls=True` unconditionally. Against
a relay on 465 (implicit SMTPS) or an internal relay without STARTTLS that fails
every single time — and the failure mode is a broad `except` that only logs, so
the most important fallback channel in the cascade was silently dead for those
topologies. Nothing in the suite covered it because nothing configured SMTP.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.alerts.notifier import send_smtp

_PAYLOAD = {"severity": "critical", "path": "/etc/passwd"}


def _cfg(**overrides) -> SimpleNamespace:
    defaults = dict(
        smtp_host="relay.local",
        smtp_port=587,
        smtp_user="fim",
        smtp_password="secret",
        smtp_from="fim@local",
        smtp_to="soc@local",
        smtp_starttls=True,
        smtp_ssl=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def _send(cfg) -> tuple[bool, dict]:
    """Run send_smtp against a stubbed aiosmtplib and return (result, kwargs)."""
    sender = AsyncMock(return_value=None)
    with patch("aiosmtplib.send", sender):
        result = await send_smtp(_PAYLOAD, cfg)
    kwargs = sender.await_args.kwargs if sender.await_args else {}
    return result, kwargs


async def test_starttls_is_the_default_and_matches_previous_behaviour() -> None:
    """Zero-step migration: unconfigured deployments behave exactly as before."""
    result, kwargs = await _send(_cfg())

    assert result is True
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False


async def test_implicit_tls_for_smtps_relay() -> None:
    """Port 465 speaks TLS from the first byte; STARTTLS must not be attempted."""
    result, kwargs = await _send(_cfg(smtp_port=465, smtp_ssl=True, smtp_starttls=False))

    assert result is True
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False


async def test_implicit_tls_wins_when_starttls_left_at_default() -> None:
    """
    smtp_starttls defaults to True, so an operator enabling only smtp_ssl would
    otherwise hit the mutually-exclusive error. That is the intended behaviour —
    the config IS contradictory — and this test pins it so the rule is explicit
    rather than incidental.
    """
    result, _ = await _send(_cfg(smtp_ssl=True))  # smtp_starttls still True

    assert result is False


async def test_plain_relay_without_tls() -> None:
    """An internal relay with no TLS at all used to fail 100% of the time."""
    result, kwargs = await _send(_cfg(smtp_starttls=False, smtp_ssl=False))

    assert result is True
    assert kwargs["use_tls"] is False
    assert kwargs["start_tls"] is False


async def test_contradictory_config_is_rejected_without_sending() -> None:
    """Both flags on is an operator error — say so, do not silently pick one."""
    sender = AsyncMock()
    with patch("aiosmtplib.send", sender):
        result = await send_smtp(_PAYLOAD, _cfg(smtp_ssl=True, smtp_starttls=True))

    assert result is False
    sender.assert_not_awaited(), "no debe intentarse el envío con configuración inválida"


async def test_missing_host_still_skips() -> None:
    result, _ = await _send(_cfg(smtp_host=""))
    assert result is False


async def test_smtp_body_carries_the_full_contract_payload() -> None:
    """
    5.4 — the fallback must not deliver less than the primary channel.

    A cascade whose fallback strips the forensic context would satisfy "delivery
    guaranteed" on paper while losing the reason the alert mattered.
    """
    from datetime import datetime, timedelta, timezone

    from app.modules.alerts.models import Alert, AlertSeverity
    from app.modules.alerts.service import _build_payload
    from app.modules.events.models import Event, EventStatus

    now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    payload = _build_payload(
        Alert(id=1, event_id=7, severity=AlertSeverity.critical, created_at=now),
        Event(
            id=7,
            event_id="e4f1c2a0-0000-4000-8000-000000000001",
            agent_id="agent-01",
            path="/etc/passwd",
            status=EventStatus.auto_restored,
            is_symlink=False,
            action_failed=False,
            process_pid=4242,
            process_uid=0,
            process_exe="/usr/bin/curl",
            detected_at=now,
            received_at=now + timedelta(milliseconds=120),
        ),
    )

    sender = AsyncMock(return_value=None)
    with patch("aiosmtplib.send", sender):
        assert await send_smtp(payload, _cfg()) is True

    body = sender.await_args.args[0].get_payload(decode=True).decode("utf-8")
    for field in ("process_pid", "process_exe", "action_taken", "received_at"):
        assert field in body, f"el fallback SMTP perdió {field}"
