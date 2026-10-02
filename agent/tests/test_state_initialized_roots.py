"""D80/RN-174: `initialized_roots` persistence in state.json (Change 62, D-5)."""
from __future__ import annotations

import json
from pathlib import Path

from agent.state import AgentState, load_state, save_state


def test_initialized_roots_round_trip_sorted(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = AgentState(state_path=path, initialized_roots=["/z", "/a"])
    save_state(state)

    assert json.loads(path.read_text())["initialized_roots"] == ["/a", "/z"]
    assert load_state(path).initialized_roots == ["/a", "/z"]


def test_state_without_key_loads_empty_list_and_is_not_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"ruleset_version": 3, "last_stream_command_id": "5-0", "rules": []}))

    state = load_state(path)

    assert state.initialized_roots == []
    assert state.ruleset_version == 3
    assert path.exists()
    assert not list(tmp_path.glob("*.bak"))


def test_invalid_shape_degrades_to_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"initialized_roots": "/etc", "ruleset_version": 2}))

    state = load_state(path)

    assert state.initialized_roots == []
    assert state.ruleset_version == 2
    assert path.exists()


def test_cursor_and_rules_persistence_keep_initialized_roots(tmp_path: Path) -> None:
    from agent.rules import RulesCache

    path = tmp_path / "state.json"
    state = AgentState(state_path=path, initialized_roots=["/etc"])
    save_state(state)

    state.last_stream_command_id = "9-0"
    save_state(state)
    assert load_state(path).initialized_roots == ["/etc"]

    cache = RulesCache(path)
    assert cache.update([{"pattern": "/etc/*", "action": "alert_only"}], 1, state) is True
    assert load_state(path).initialized_roots == ["/etc"]
