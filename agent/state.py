from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_STATE_PATH = Path("/var/lib/fim-agent/state.json")


@dataclass
class AgentState:
    ruleset_version: int = 0
    last_stream_command_id: str = "0-0"
    rules: list = field(default_factory=list)
    state_path: Path = field(
        default_factory=lambda: _DEFAULT_STATE_PATH, compare=False, repr=False
    )


def load_state(path: Path = _DEFAULT_STATE_PATH) -> AgentState:
    if not path.exists():
        return AgentState(state_path=path)
    try:
        data = json.loads(path.read_text())
        return AgentState(
            ruleset_version=int(data.get("ruleset_version", 0)),
            last_stream_command_id=data.get("last_stream_command_id", "0-0"),
            rules=data.get("rules", []),
            state_path=path,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"State file corrupt: {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def save_state(state: AgentState, path: Path | None = None) -> None:
    target = path or state.state_path
    tmp = target.with_suffix(".tmp")
    payload = json.dumps({
        "ruleset_version": state.ruleset_version,
        "last_stream_command_id": state.last_stream_command_id,
        "rules": state.rules,
    })
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
    except Exception:
        raise
    os.replace(tmp, target)
    os.chmod(target, 0o600)
