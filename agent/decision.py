"""Motor de decisión: evalúa reglas, ejecuta acciones, journaliza (C10, RN-05–07/30–37/42/65/83)."""
from __future__ import annotations

import base64
import errno
import hashlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

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


def parse_baseline_mode(value: str | None) -> int | None:
    """Parsea el `mode` guardado en la entry del baseline (D36/RN-130, D-6).

    Acepta la forma con prefijo que produce `oct(stat.S_IMODE(...))`
    (`'0o644'`, `agent/baseline.py:293`) y el octal desnudo (`'644'`).
    Devuelve None ante cualquier otra cosa — ausencia o basura enrutan al
    mismo fallo (`no_baseline_metadata`) en vez de a un default silencioso.
    Preserva los bits setuid/setgid/sticky: `S_IMODE` ya cubre 0o7777.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = int(value, 8)
    except ValueError:
        return None
    if not (0 <= parsed <= 0o7777):
        return None
    return parsed


def action_error_from_oserror(exc: OSError, *, fallback: str) -> str:
    """Mapea un OSError real al vocabulario cerrado de `_ActionFailed` (D36/RN-130, D-7).

    `errno.EROFS` -> `read_only_mount` (barrera de mount, D36).
    `errno.EACCES` / `errno.EPERM` -> `permission_denied` (barrera DAC, D36).
    Cualquier otro -> el `fallback` del sitio de la llamada.
    """
    if exc.errno == errno.EROFS:
        return "read_only_mount"
    if exc.errno in (errno.EACCES, errno.EPERM):
        return "permission_denied"
    return fallback


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

    def evaluate_and_act(
        self, change: "DetectedChange"
    ) -> tuple[dict[str, Any], Callable[[], None]]:
        """Evalúa acción, journaliza pending, ejecuta. Retorna (payload, commit_fn).

        commit_fn aplica la transición terminal del journal (completed/failed).
        El caller DEBE invocar commit_fn() solo tras un publish exitoso; si el
        publish falla, la entrada queda pending y se rehidrata al reiniciar (FA3).
        """
        action = self._rules.evaluate(change.path)
        self._journal.write_pending(change.event_id, change.path, action)

        payload = change.to_event_data()
        payload["action"] = action

        event_id = change.event_id
        try:
            if action == "auto_restore":
                self._auto_restore(event_id, change.path, payload)
            elif action == "quarantine":
                self._quarantine(event_id, change.path, payload)
            # manual_review y alert_only: sin acción física

            def commit_fn() -> None:
                self._journal.mark_completed(event_id)
                self._journal.delete(event_id)

        except _ActionFailed as exc:
            payload["action_failed"] = True
            # D36/RN-130 (D-7): la causa viaja al lado del booleano. No se
            # escribe en la ruta de éxito, mismo criterio que action_failed,
            # para que todo consumidor la lea con .get(...).
            payload["action_error"] = exc.error
            _error = exc.error

            def commit_fn() -> None:  # type: ignore[no-redef]
                self._journal.mark_failed(event_id, _error)

        log.info(
            "decision.evaluated",
            event_id=event_id,
            path=change.path,
            action=action,
            action_failed=payload.get("action_failed", False),
        )
        return payload, commit_fn

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
                "hash_expected": None,
                # D-C13-04: "" = hash ausente. hash_detected es str NOT NULL en el
                # modelo Event del backend; nunca emitir None (evita IntegrityError + poison loop).
                "hash_detected": "",
                "diff_text": None,
                # D49/RN-143: los tres campos de proceso van en None. En esta ruta
                # el proceso causante ya no existe POR DEFINICIÓN — la rehidratación
                # corre tras un reinicio del agente —, así que el contexto es
                # irrecuperable. `0` en process_uid significa root; escribirlo acá
                # haría que TODO evento recuperado del journal se reportara como
                # hecho por root. Por la misma razón, `0` en process_pid tampoco es
                # dato: es el pid del scheduler del kernel, no el de un proceso de
                # usuario.
                "process_pid": None,
                "process_uid": None,
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
                except _ActionFailed as exc:
                    payload["action_failed"] = True
                    payload["action_error"] = exc.error
                except Exception as exc:
                    log.warning(
                        "decision.rehydrate.unexpected",
                        event_id=entry.event_id,
                        error=str(exc),
                    )
                    continue
            else:
                # manual_review o alert_only: sin acción, se re-publican como alert_only
                payload["action"] = "alert_only"

            try:
                await publisher.publish(payload)
            except Exception as pub_exc:
                log.warning(
                    "decision.rehydrate.publish_failed",
                    event_id=entry.event_id,
                    error=str(pub_exc),
                )
                # El journal sigue pending: publish() solo retorna cuando el
                # evento quedó encolado durablemente. Si ni siquiera se pudo
                # encolar, terminalizar acá perdería la única evidencia apta
                # para reintentar en el próximo arranque.
                continue

            if payload.get("action_failed"):
                self._journal.mark_failed(
                    entry.event_id,
                    str(payload.get("action_error", "rehydrated_action_failed")),
                )
            elif entry.action in ("auto_restore", "quarantine"):
                self._journal.mark_completed(entry.event_id)
                self._journal.delete(entry.event_id)
            else:
                self._journal.mark_failed(entry.event_id, "rehydrated_without_action")
            log.info(
                "decision.rehydrate.entry",
                event_id=entry.event_id,
                original_action=entry.action,
                action_failed=payload.get("action_failed", False),
            )

    # ── acciones privadas ─────────────────────────────────────────────────────

    def _auto_restore(self, event_id: str, path: str, payload: dict[str, Any]) -> None:
        """Restaura archivo desde baseline o snapshot, incluida su metadata (RN-30–33, D36/RN-130 D-6).

        Verifica SHA-256 igual que antes. Además restaura mode/uid/gid desde la
        entry del baseline: sin esto, habilitar las capabilities de escritura
        convierte un feature roto en una vulnerabilidad (D-6 del design).
        """
        from agent.baseline import select_restorable_content

        entry = self._baseline.read_entry(path)
        if entry is None:
            raise _ActionFailed("no_baseline_content")

        result = select_restorable_content(entry)
        if result is None:
            raise _ActionFailed("no_restorable_content")

        content, expected_hash = result

        # D36/RN-130 (D-6): metadata ausente => la restauración FALLA, nunca
        # se completa a medias. mark_absent produce entries con las tres en
        # None (agent/baseline.py:351-360); publicar un archivo del sistema
        # con dueño fim-agent y modo por umask es peor que no restaurarlo.
        mode = parse_baseline_mode(entry.mode)
        uid = entry.uid
        gid = entry.gid
        if mode is None or uid is None or gid is None:
            raise _ActionFailed("no_baseline_metadata")

        tmp_path = path + ".fim_restore_tmp"

        # O_EXCL: un .fim_restore_tmp huérfano de un intento previo hace
        # fallar el intento en vez de truncarlo y reusarlo. No se toca el
        # huérfano — no es nuestro para borrar si no lo abrimos nosotros.
        try:
            fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        except OSError as exc:
            raise _ActionFailed(action_error_from_oserror(exc, fallback="write_failed")) from exc

        try:
            os.write(fd, content)
            os.fsync(fd)
            # D36/RN-130 (D-6): fchown ANTES que fchmod, en ese orden, sobre
            # el descriptor (no por path — elimina el TOCTOU sobre el tmp).
            # chown(2) LIMPIA los bits setuid/setgid de un archivo. Invertir
            # este orden produce una restauración que reporta éxito y deja
            # un binario privilegiado (p.ej. /usr/bin/sudo) sin su bit
            # setuid. No reordenar esto "por prolijidad".
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
        except OSError as exc:
            os.close(fd)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise _ActionFailed(action_error_from_oserror(exc, fallback="write_failed")) from exc
        else:
            os.close(fd)

        try:
            os.replace(tmp_path, path)
        except OSError as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise _ActionFailed(action_error_from_oserror(exc, fallback="write_failed")) from exc

        restored_hash = _hash_bytes(content)
        if expected_hash and restored_hash != expected_hash:
            raise _ActionFailed("hash_mismatch_after_restore")

    def _quarantine(self, event_id: str, path: str, payload: dict[str, Any]) -> None:
        """Mueve archivo a directorio de cuarentena (RN-34–37)."""
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)
        basename = os.path.basename(path)
        quarantine_path = str(self._quarantine_dir / f"{event_id}_{basename}")
        try:
            shutil.move(path, quarantine_path)
        except FileNotFoundError:
            raise _ActionFailed("file_not_found")
        except OSError as exc:
            raise _ActionFailed(action_error_from_oserror(exc, fallback="move_failed")) from exc
        payload["quarantine_path"] = quarantine_path
