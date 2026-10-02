"""
Token bucket ingest rate limit (D85/RN-179, change `ingest-token-bucket-rate-limit`).

Pure unit tests with an injected clock — no sleeping, no database. The consumer
integration scenario lives in `test_event_consumer_c11.py` next to its harness.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, legacy_ingest_rate_limit_vars
from app.modules.events.consumer import _RateLimiter

RATE = 100 / 60
BURST = 3000
REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeClock:
    """Injectable monotonic clock: tests advance time explicitly."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _drain(limiter: _RateLimiter, key: str) -> int:
    admitted = 0
    while limiter.check(key):
        admitted += 1
    return admitted


# ── 5.1 Burst ──────────────────────────────────────────────────────────────────


def test_full_bucket_admits_the_burst_and_rejects_the_next() -> None:
    limiter = _RateLimiter(rate_per_s=RATE, burst=BURST, clock=_FakeClock())

    assert all(limiter.check("agent-a") for _ in range(BURST))
    assert limiter.check("agent-a") is False


def test_battery5_replay_is_admitted_without_rejections() -> None:
    """The 2,672-event replay measured in battery 5 fits in the burst."""
    limiter = _RateLimiter(rate_per_s=RATE, burst=BURST, clock=_FakeClock())

    assert all(limiter.check("agent-a") for _ in range(2672))


# ── 5.2 Sustained regime ───────────────────────────────────────────────────────


def test_sustained_regime_is_100_events_per_minute() -> None:
    clock = _FakeClock()
    limiter = _RateLimiter(rate_per_s=RATE, burst=BURST, clock=clock)
    _drain(limiter, "agent-a")

    admitted = 0
    for _ in range(6000):  # 600 s in 0.1 s steps
        clock.advance(0.1)
        if limiter.check("agent-a"):
            admitted += 1

    assert admitted == pytest.approx(1000, abs=1)


# ── 5.3 Refill ceiling ─────────────────────────────────────────────────────────


def test_refill_is_capped_at_the_burst() -> None:
    clock = _FakeClock()
    limiter = _RateLimiter(rate_per_s=RATE, burst=BURST, clock=clock)
    _drain(limiter, "agent-a")

    clock.advance(7200)  # far longer than the 30 min needed to refill

    assert _drain(limiter, "agent-a") == BURST


# ── 5.4 Per-agent isolation ────────────────────────────────────────────────────


def test_agents_do_not_share_a_bucket() -> None:
    limiter = _RateLimiter(rate_per_s=RATE, burst=BURST, clock=_FakeClock())
    _drain(limiter, "agent-a")
    assert limiter.seconds_until_available("agent-a") > 0

    assert limiter.check("agent-b") is True
    assert sum(limiter.check("agent-b") for _ in range(BURST)) == BURST - 1


def test_untouched_agent_reports_no_wait_while_another_is_in_deficit() -> None:
    limiter = _RateLimiter(rate_per_s=RATE, burst=BURST, clock=_FakeClock())
    _drain(limiter, "agent-a")

    assert limiter.seconds_until_available("agent-b") == 0.0
    assert "agent-b" not in limiter._buckets


# ── 5.6 Settings ───────────────────────────────────────────────────────────────


def test_settings_reject_non_positive_rate(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_INGEST_RATE_PER_S", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_burst_below_one(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_INGEST_BURST", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_settings_feed_the_limiter(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_INGEST_BURST", "3")
    monkeypatch.setenv("RATE_LIMIT_INGEST_RATE_PER_S", "0.5")
    cfg = Settings()
    import app.modules.events.consumer as consumer_mod

    monkeypatch.setattr(consumer_mod, "settings", cfg)
    limiter = consumer_mod._RateLimiter(clock=_FakeClock())

    assert [limiter.check("a1") for _ in range(4)] == [True, True, True, False]
    assert limiter.seconds_until_available("a1") == pytest.approx(2.0)


# ── 5.7 Legacy variables warning ───────────────────────────────────────────────


def test_legacy_vars_defined_in_environment() -> None:
    assert legacy_ingest_rate_limit_vars({"RATE_LIMIT_INGEST_EVENTS": "100000"}, {}) == [
        "RATE_LIMIT_INGEST_EVENTS"
    ]


def test_legacy_vars_defined_only_in_env_file() -> None:
    assert legacy_ingest_rate_limit_vars({}, {"RATE_LIMIT_INGEST_WINDOW_SECONDS": "60"}) == [
        "RATE_LIMIT_INGEST_WINDOW_SECONDS"
    ]


def test_legacy_vars_empty_or_none_count_as_undefined() -> None:
    environ = {"RATE_LIMIT_INGEST_EVENTS": ""}
    env_file = {"RATE_LIMIT_INGEST_WINDOW_SECONDS": None}
    assert legacy_ingest_rate_limit_vars(environ, env_file) == []


def test_legacy_vars_names_are_case_insensitive() -> None:
    assert legacy_ingest_rate_limit_vars({"rate_limit_ingest_events": "5"}, {}) == [
        "RATE_LIMIT_INGEST_EVENTS"
    ]


def test_legacy_vars_both_names_in_fixed_order_without_duplicates() -> None:
    environ = {"RATE_LIMIT_INGEST_WINDOW_SECONDS": "60", "RATE_LIMIT_INGEST_EVENTS": "1"}
    env_file = {"RATE_LIMIT_INGEST_EVENTS": "2"}
    assert legacy_ingest_rate_limit_vars(environ, env_file) == [
        "RATE_LIMIT_INGEST_EVENTS",
        "RATE_LIMIT_INGEST_WINDOW_SECONDS",
    ]


def test_legacy_vars_none_defined() -> None:
    assert legacy_ingest_rate_limit_vars({"PATH": "/bin"}, {"OTHER": "x"}) == []


# `_warn_legacy_ingest_rate_limit_vars` is extracted from `lifespan` for the same
# reason as `_log_console_tls_mode` (see test_auth_cookie_console_mode.py): it
# avoids booting Valkey, the CA and the consumers just to observe a startup log.


def test_startup_warns_once_when_legacy_variable_is_set(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module

    monkeypatch.setenv("RATE_LIMIT_INGEST_EVENTS", "100000")
    monkeypatch.delenv("RATE_LIMIT_INGEST_WINDOW_SECONDS", raising=False)
    fake_log = MagicMock()
    monkeypatch.setattr(main_module, "log", fake_log)

    main_module._warn_legacy_ingest_rate_limit_vars()

    fake_log.warning.assert_called_once()
    args, kwargs = fake_log.warning.call_args
    assert args[0] == "config.legacy_ingest_rate_limit_ignored"
    assert kwargs["variables"] == ["RATE_LIMIT_INGEST_EVENTS"]
    assert kwargs["replacements"] == ["RATE_LIMIT_INGEST_RATE_PER_S", "RATE_LIMIT_INGEST_BURST"]


def test_startup_does_not_warn_without_legacy_variables(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module

    monkeypatch.delenv("RATE_LIMIT_INGEST_EVENTS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_INGEST_WINDOW_SECONDS", raising=False)
    monkeypatch.setitem(main_module.Settings.model_config, "env_file", None)
    fake_log = MagicMock()
    monkeypatch.setattr(main_module, "log", fake_log)

    main_module._warn_legacy_ingest_rate_limit_vars()

    fake_log.warning.assert_not_called()


def test_lifespan_invokes_the_legacy_warning() -> None:
    import inspect

    import app.main as main_module

    assert "_warn_legacy_ingest_rate_limit_vars()" in inspect.getsource(main_module.lifespan)


# ── 5.8 Compose aligned with Settings ──────────────────────────────────────────


def _compose_default(name: str) -> str:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    match = re.search(rf"^\s*{name}:\s*\$\{{{name}:-([^}}]*)\}}\s*$", text, re.MULTILINE)
    assert match, f"{name} is not forwarded with a default in docker-compose.yml"
    return match.group(1)


def test_compose_defaults_match_settings() -> None:
    rate = Settings.model_fields["rate_limit_ingest_rate_per_s"].default
    burst = Settings.model_fields["rate_limit_ingest_burst"].default

    assert float(_compose_default("RATE_LIMIT_INGEST_RATE_PER_S")) == pytest.approx(rate, rel=1e-12)
    assert int(_compose_default("RATE_LIMIT_INGEST_BURST")) == burst


def test_compose_forwards_legacy_names_with_empty_default() -> None:
    assert _compose_default("RATE_LIMIT_INGEST_EVENTS") == ""
    assert _compose_default("RATE_LIMIT_INGEST_WINDOW_SECONDS") == ""
