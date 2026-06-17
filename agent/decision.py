"""Motor de decisión: evalúa reglas, ejecuta acciones, journaliza (C10, RN-05–07/30–37/42/65/83)."""
from __future__ import annotations

import base64
import hashlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from agent.journal import JournalManager
from agent.rules import RulesCache

if TYPE_CHECKING:
    from agent.baseline import BaselineEngine
    from agent.detector import DetectedChange
    from agent.publisher import Publisher

log = structlog.get_logger()


class _ActionFailed(Exception):
    """Señala fallo en la ejecución de una acción."""
    def __init__(self, error: str) -> None:
        self.error = error
        super().__init__(error)


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class DecisionEngine:
    """Orquesta evaluación de reglas + ejecución de acciones + journal transaccional."""

    def __init__(
        self,
        rules: RulesCache,
        journal: JournalManager,
        baseline: "BaselineEngine",
        quarantine_dir: str | Path,
    ) -> None:
        self._rules = rules
        self._journal = journal
        self._baseline = baseline
        self._quarantine_dir = Path(quarantine_dir)

    # ── API pública ───────────────────────────────────────────────────────────

    def evaluate_and_act(self, change: "DetectedChange") -> dict[str, Any]:
        """Evalúa acción, journaliza pending, ejecuta, actualiza journal. Retorna payload enriquecido."""
        action = self._rules.evaluate(change.path)
        self._journal.write_pending(change.event_id, change.path, action)

        payload = change.to_event_data()
        payload["action"] = action

        try:
            if action == "auto_restore":
                self._auto_restore(change.event_id, change.path, payload)
            elif action == "quarantine":
                self._quarantine(change.event_id, change.path, payload)
            # manual_review y alert_only: sin acción física
            self._journal.mark_completed(change.event_id)
        except _ActionFailed as exc:
            self._journal.mark_failed(change.event_id, exc.error)
            payload["action_failed"] = True

        log.info(
            "decision.evaluated",
            event_id=change.event_id,
            path=change.path,
            action=action,
            action_failed=payload.get("action_failed", False),
        )
        return payload

    async def rehydrate(self, publisher: "Publisher") -> None:
        """Rehidrata journal pending al arrancar: reintenta automáticas, descarta manuales (RN-83)."""
        pending = self._journal.load_pending()
        if not pending:
            return
        log.info("decision.rehydrate.start", count=len(pending))
        for entry in pending:
            payload: dict[str, Any] = {
                "event_id": entry.event_id,
                "path": entry.path,
                "event_type": "file_modified",
                "previous_hash": None,
                "current_hash": None,
                "diff_text": None,
                "process_pid": 0,
                "process_uid": 0,
                "process_exe": None,
                "detected_at": entry.created_at,
                "parent_event_id": None,
                "action": entry.action,
            }
            if entry.action in ("auto_restore", "quarantine"):
                try:
                    if entry.action == "auto_restore":
                        self._auto_restore(entry.event_id, entry.path, payload)
                    else:
                        self._quarantine(entry.event_id, entry.path, payload)
                    self._journal.mark_completed(entry.event_id)
                    self._journal.delete(entry.event_id)
                except _ActionFailed as exc:
                    self._journal.mark_failed(entry.event_id, exc.error)
                    payload["action_failed"] = True
            else:
                # manual_review o alert_only: fallan sin acción, se re-publican como alert_only
                self._journal.mark_failed(entry.event_id, "rehydrated_without_action")
                payload["action"] = "alert_only"

            await publisher.publish(payload)
            log.info(
                "decision.rehydrate.entry",
                event_id=entry.event_id,
                original_action=entry.action,
                action_failed=payload.get("action_failed", False),
            )

    # ── acciones privadas ─────────────────────────────────────────────────────

    def _auto_restore(self, event_id: str, path: str, payload: dict[str, Any]) -> None:
        """Restaura archivo desde content_b64 del baseline. Verifica SHA-256 (RN-30–33)."""
        entry = self._baseline.read_entry(path)
        if entry is None or entry.content_b64 is None:
            raise _ActionFailed("no_baseline_content")

        content = base64.b64decode(entry.content_b64)

        tmp_path = path + ".fim_restore_tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(content)
            os.replace(tmp_path, path)
        except OSError as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise _ActionFailed(f"write_failed: {exc}") from exc

        restored_hash = _hash_bytes(content)
        if entry.hash and restored_hash != entry.hash:
            raise _ActionFailed("hash_mismatch_after_restore")

        payload["event_type"] = "auto_restored"

    def _quarantine(self, event_id: str, path: str, payload: dict[str, Any]) -> None:
        """Mueve archivo a directorio de cuarentena (RN-34–37)."""
        basename = os.path.basename(path)
        quarantine_path = str(self._quarantine_dir / f"{event_id}_{basename}")
        try:
            shutil.move(path, quarantine_path)
        except FileNotFoundError:
            raise _ActionFailed("file_not_found")
        except OSError as exc:
            raise _ActionFailed(f"move_failed: {exc}") from exc
        payload["quarantine_path"] = quarantine_path
