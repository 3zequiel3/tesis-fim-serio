"""Cache local de reglas de decisión con evaluación glob (C10, RN-05/06/65)."""
from __future__ import annotations

import dataclasses
import fnmatch
import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from agent.state import AgentState

log = structlog.get_logger()


@dataclasses.dataclass
class Rule:
    pattern: str
    action: str | None  # None para reglas exclusivas
    negated: bool


class RulesCache:
    """Cache de reglas de decisión. Se actualiza vía rule_sync firmado (RN-75, RN-79)."""

    def __init__(self, state_path: Path) -> None:
        self._rules: list[Rule] = []
        self._state_path = state_path
        self._lock = threading.Lock()
        self._load_from_file()

    # ── carga ─────────────────────────────────────────────────────────────────

    def _load_from_file(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text())
            self.load(data)
        except Exception as exc:
            log.warning("rules_cache.load_failed", error=str(exc))

    def load(self, state_dict: dict) -> None:
        """Popula la cache desde el dict de state.json (clave 'rules')."""
        raw = state_dict.get("rules", [])
        with self._lock:
            self._rules = [
                Rule(
                    pattern=r.get("pattern", ""),
                    action=r.get("action"),
                    negated=bool(r.get("negated", False)),
                )
                for r in raw
                if r.get("pattern")
            ]

    # ── evaluación ────────────────────────────────────────────────────────────

    def evaluate(self, path: str) -> str:
        """Evalúa path contra reglas en orden. Exclusiva (!) gana. Default alert_only (RN-06)."""
        with self._lock:
            rules = list(self._rules)
        result_action: str | None = None
        for rule in rules:
            match_pattern = rule.pattern[1:] if rule.negated else rule.pattern
            if fnmatch.fnmatch(path, match_pattern):
                if rule.negated:
                    return "alert_only"  # exclusiva gana inmediatamente (RN-65)
                elif result_action is None:
                    result_action = rule.action or "alert_only"
        return result_action or "alert_only"

    # ── actualización ─────────────────────────────────────────────────────────

    def update(
        self,
        rules_payload: list[dict],
        ruleset_version: int,
        state: "AgentState",
    ) -> bool:
        """Reemplaza reglas si la versión es mayor. Actualiza state en memoria y persiste."""
        if ruleset_version < state.ruleset_version:
            log.info(
                "rules_cache.update_skipped",
                current=state.ruleset_version,
                received=ruleset_version,
            )
            return False
        with self._lock:
            self._rules = [
                Rule(
                    pattern=r.get("pattern", ""),
                    action=r.get("action"),
                    negated=bool(r.get("negated", False)),
                )
                for r in rules_payload
                if r.get("pattern")
            ]
        state.ruleset_version = ruleset_version
        self._persist(state)
        log.info("rules_cache.updated", ruleset_version=ruleset_version, count=len(self._rules))
        return True

    # ── persistencia ──────────────────────────────────────────────────────────

    def _persist(self, state: "AgentState") -> None:
        """Actualiza state.rules y delega la escritura a save_state (punto único de escritura)."""
        from agent.state import save_state

        with self._lock:
            rules_data = [
                {"pattern": r.pattern, "action": r.action, "negated": r.negated}
                for r in self._rules
            ]
        state.rules = rules_data
        save_state(state)
