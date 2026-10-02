from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger()

_DEFAULT_STATE_PATH = Path("/var/lib/fim-agent/state.json")


@dataclass
class AgentState:
    ruleset_version: int = 0
    last_stream_command_id: str = "0-0"
    rules: list = field(default_factory=list)
    # D80/RN-174: watch roots that completed a first scan. Only these are
    # reconciled against the baseline on start; absent in old state files.
    initialized_roots: list[str] = field(default_factory=list)
    state_path: Path = field(
        default_factory=lambda: _DEFAULT_STATE_PATH, compare=False, repr=False
    )


def load_state(path: Path = _DEFAULT_STATE_PATH) -> AgentState:
    if not path.exists():
        return AgentState(state_path=path)
    try:
        data = json.loads(path.read_text())
        raw_roots = data.get("initialized_roots", [])
        if isinstance(raw_roots, list) and all(isinstance(r, str) for r in raw_roots):
            initialized_roots = list(raw_roots)
        else:
            log.warning("state.initialized_roots_invalid")
            initialized_roots = []
        return AgentState(
            ruleset_version=int(data.get("ruleset_version", 0)),
            last_stream_command_id=data.get("last_stream_command_id", "0-0"),
            rules=data.get("rules", []),
            initialized_roots=initialized_roots,
            state_path=path,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        bak = path.with_name(f"state.{int(time.time())}.json.bak")
        try:
            path.rename(bak)
        except OSError as rename_exc:
            log.warning("state.load_corrupt.rename_failed", path=str(path), error=str(rename_exc))
        log.warning(
            "state.load_corrupt",
            path=str(path),
            backup=str(bak),
            error=str(exc),
        )
        print(
            f"State file corrupt (renamed to {bak}): {path}: {exc}",
            file=sys.stderr,
        )
        return AgentState(state_path=path)


def save_state(state: AgentState, path: Path | None = None) -> None:
    target = path or state.state_path
    tmp = target.with_suffix(".tmp")
    payload = json.dumps({
        "ruleset_version": state.ruleset_version,
        "last_stream_command_id": state.last_stream_command_id,
        "rules": state.rules,
        "initialized_roots": sorted(state.initialized_roots),
    })
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        raise
    os.replace(tmp, target)
    os.chmod(target, 0o600)
