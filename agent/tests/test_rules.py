"""Tests de RulesCache (C10, task 8.1–8.5)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.rules import Rule, RulesCache


def _make_cache(tmp_path: Path, rules: list[dict] | None = None) -> RulesCache:
    state_path = tmp_path / "state.json"
    if rules is not None:
        state_path.write_text(json.dumps({"ruleset_version": 0, "rules": rules}))
    else:
        state_path.write_text(json.dumps({"ruleset_version": 0}))
    return RulesCache(state_path)


def test_rules_evaluate_inclusive_match(tmp_path: Path) -> None:
    cache = _make_cache(tmp_path, rules=[
        {"pattern": "/etc/**", "action": "auto_restore", "negated": False},
    ])
    assert cache.evaluate("/etc/hosts") == "auto_restore"


def test_rules_evaluate_exclusive_wins(tmp_path: Path) -> None:
    cache = _make_cache(tmp_path, rules=[
        {"pattern": "/etc/**", "action": "auto_restore", "negated": False},
        {"pattern": "!/etc/mtab", "action": None, "negated": True},
    ])
    assert cache.evaluate("/etc/mtab") == "alert_only"


def test_rules_evaluate_no_match_default(tmp_path: Path) -> None:
    cache = _make_cache(tmp_path, rules=[
        {"pattern": "/etc/**", "action": "auto_restore", "negated": False},
    ])
    assert cache.evaluate("/tmp/foo.txt") == "alert_only"


def test_rules_update_rejects_older_version(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ruleset_version": 5, "rules": []}))
    cache = RulesCache(state_path)

    state = MagicMock()
    state.ruleset_version = 5

    updated = cache.update(
        [{"pattern": "/etc/**", "action": "quarantine", "negated": False}],
        ruleset_version=3,
        state=state,
    )

    assert updated is False
    assert cache.evaluate("/etc/hosts") == "alert_only"  # reglas sin cambio


def test_rules_update_applies_newer_version(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ruleset_version": 2, "rules": []}))
    cache = RulesCache(state_path)

    state = MagicMock()
    state.ruleset_version = 2

    updated = cache.update(
        [{"pattern": "/opt/**", "action": "quarantine", "negated": False}],
        ruleset_version=3,
        state=state,
    )

    assert updated is True
    assert cache.evaluate("/opt/app/evil.sh") == "quarantine"

    # Verificar que se persistió
    saved = json.loads(state_path.read_text())
    assert saved["ruleset_version"] == 3
    assert len(saved["rules"]) == 1
    assert saved["rules"][0]["pattern"] == "/opt/**"
