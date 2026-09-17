"""D73/RN-167: the agent MUST filter its structlog output by the configured
level (`--log-level`, overridable by `LOG_LEVEL`), the same mechanism the
backend already uses (`structlog.make_filtering_bound_logger`).

D69/RN-163 lowered `detector.out_of_scope_drop` from `warning` to `debug`
assuming that would stop it from flooding the agent journal. It did not:
`configure_logging` (agent/logging.py) never filtered by level —
`wrapper_class=structlog.stdlib.BoundLogger` plus
`logger_factory=structlog.PrintLoggerFactory` prints every level regardless
of `--log-level`/`LOG_LEVEL` — so the journal kept flooding after that
change was deployed (82 "debug" lines measured in the 15s after the
2026-09-17 deploy). `detector.out_of_scope_drop` is the motivating case for
every assertion below.
"""

from __future__ import annotations

import structlog
import pytest

from agent.logging import configure_logging


@pytest.fixture(autouse=True)
def _reset_structlog_defaults():
    """Each test reconfigures global structlog state; reset it afterwards so
    tests in other modules never see a filtering wrapper_class left behind.
    """
    yield
    structlog.reset_defaults()


def test_info_level_drops_debug_lines(capsys, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging(level="info", fmt="json")

    log = structlog.get_logger()
    log.debug("detector.out_of_scope_drop", path="/tmp/x", total_drops=1)
    log.info("agent.started")

    out = capsys.readouterr().out
    assert "detector.out_of_scope_drop" not in out
    assert "agent.started" in out


def test_debug_level_keeps_debug_lines(capsys, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging(level="debug", fmt="json")

    log = structlog.get_logger()
    log.debug("detector.out_of_scope_drop", path="/tmp/x", total_drops=1)

    out = capsys.readouterr().out
    assert "detector.out_of_scope_drop" in out


def test_log_level_env_var_overrides_default(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    configure_logging(level="info", fmt="json")

    log = structlog.get_logger()
    log.debug("detector.out_of_scope_drop", path="/tmp/x", total_drops=1)

    out = capsys.readouterr().out
    assert "detector.out_of_scope_drop" in out


def test_unknown_level_falls_back_to_info(capsys, monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    configure_logging(level="not-a-real-level", fmt="json")

    log = structlog.get_logger()
    log.debug("detector.out_of_scope_drop", path="/tmp/x", total_drops=1)
    log.info("agent.started")

    out = capsys.readouterr().out
    assert "detector.out_of_scope_drop" not in out
    assert "agent.started" in out
