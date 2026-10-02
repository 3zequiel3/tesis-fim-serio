"""
Dispatcher de comandos entrantes del stream `commands` para el agente FIM (C13, C14).

Implementa:
  dispatch(command, *, baseline_engine, state, valkey_client, config, detector)
    — enruta por command["type"] con verificación HMAC y filtro target_agent_id.

Handlers:
  handle_baseline_update  — actualiza baseline local cifrado y publica event_ack.
  handle_restore_file     — restaura archivo desde baseline con journal.
  handle_quarantine_file  — pone en cuarentena con journal.
  handle_release_quarantine — libera una cuarentena: restore_original (aprueba),
                            restore_baseline o discard, sin sobrescribir (D83/RN-177).
  handle_update_config    — recarga watch_paths en fanotify + scan de paths nuevos (C14).
  handle_rescan_baseline  — scan de baseline: todos los watch_paths, o solo
                            los paths indicados por el comando (C14, US-22).

Restricciones:
  - Sin servidor HTTP (D8, RN-108).
  - Verificación HMAC-SHA256 sobre JSON canónico (sin campo signature).
  - Filtro target_agent_id: None = broadcast; otro valor = solo ese agente.
  - event_ack publicado siempre (ok o error) tras ejecutar.
  - event_ack (command_ack) firmado HMAC-SHA256 (D30/RN-79, C36, decisión del
    usuario 2026-07-02) — cierra la asimetría con los comandos entrantes,
    que ya se verifican por firma.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from agent.streams import canonical_json, sign_payload, verify_payload

if TYPE_CHECKING:
    import valkey.asyncio as avalkey

    from agent.baseline import BaselineEngine, BaselineEntry
    from agent.config import AgentConfig
    from agent.detector import FanotifyDetector
    from agent.executed_commands import ExecutedCommandRegistry
    from agent.journal import JournalManager
    from agent.preflight import PreflightRegistry
    from agent.quarantine import QuarantineStore
    from agent.state import AgentState

log = structlog.get_logger()

STREAM_EVENT_ACK = "event_ack"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _publish_ack(
    valkey_client: "avalkey.Valkey",
    command_id: str,
    command_type: str,
    event_id: Any,
    config: "AgentConfig",
    ok: bool,
    error: str | None = None,
) -> None:
    """
    Publica confirmación command_ack firmada HMAC-SHA256 al stream event_ack
    de Valkey (D30/RN-79, C36, decisión del usuario 2026-07-02).

    Si no se puede cargar el shared_secret local, se publica sin firma (fail
    -open observable, mismo criterio que dispatch()) — el consumer del
    backend rechazará el ack por firma inválida/faltante, quedando el
    comando `pending` hasta que el barrido de timeout lo marque.
    """
    payload: dict[str, Any] = {
        "command_id": command_id,
        "command_type": command_type,
        "event_id": event_id,
        "agent_id": config.agent_id,
        "status": "ok" if ok else "error",
        "error": error,
        "timestamp": _now_iso(),
    }
    secret = _load_shared_secret(config)
    if secret is None:
        log.error("commands.ack_publish.no_shared_secret", command_id=command_id)
    else:
        payload["signature"] = sign_payload(secret, payload)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    try:
        await valkey_client.xadd(STREAM_EVENT_ACK, {"data": data})
        log.debug("commands.ack_published", command_id=command_id, status=payload["status"])
    except Exception as exc:
        log.error("commands.ack_publish_failed", command_id=command_id, error=str(exc))


# ── Dispatcher principal ──────────────────────────────────────────────────────


async def dispatch(
    command: dict[str, Any],
    *,
    baseline_engine: "BaselineEngine",
    state: "AgentState",
    valkey_client: "avalkey.Valkey",
    config: "AgentConfig",
    journal: "JournalManager | None" = None,
    quarantine_dir: str | None = None,
    quarantine_store: "QuarantineStore | None" = None,
    detector: "FanotifyDetector | None" = None,
    preflight_registry: "PreflightRegistry | None" = None,
    executed_commands: "ExecutedCommandRegistry | None" = None,
) -> None:
    """
    Enruta un comando entrante del stream `commands`.

    1. Filtra target_agent_id — ignorar silenciosamente si no coincide.
    2. Verifica firma HMAC-SHA256 — descartar con log error si falla.
    3. Despacha al handler según command["type"].
    4. Tipos desconocidos: log warning, sin excepción.
    """
    # 1. Filtro target_agent_id
    target = command.get("target_agent_id")
    if target is not None and target != config.agent_id:
        log.debug("commands.dispatch.target_mismatch", target=target, own=config.agent_id)
        return

    # 2. Verificación HMAC
    secret = _load_shared_secret(config)
    if secret is None:
        log.error("commands.dispatch.no_shared_secret", agent_id=config.agent_id)
        return

    if not verify_payload(secret, command):
        log.error(
            "commands.dispatch.hmac_invalid",
            command_type=command.get("type"),
            command_id=command.get("command_id"),
        )
        return

    # 3. Dispatch por tipo
    cmd_type = command.get("type", "")

    if cmd_type == "baseline_update":
        await handle_baseline_update(
            command=command,
            baseline_engine=baseline_engine,
            state=state,
            valkey_client=valkey_client,
            config=config,
        )
    elif cmd_type == "restore_file":
        if journal is None:
            log.error("commands.dispatch.restore_no_journal")
            return
        await handle_restore_file(
            command=command,
            baseline_engine=baseline_engine,
            journal=journal,
            valkey_client=valkey_client,
            config=config,
        )
    elif cmd_type == "quarantine_file":
        if journal is None:
            log.error("commands.dispatch.quarantine_no_journal")
            return
        await handle_quarantine_file(
            command=command,
            baseline_engine=baseline_engine,
            journal=journal,
            valkey_client=valkey_client,
            config=config,
            quarantine_dir=quarantine_dir,
            quarantine_store=quarantine_store,
        )
    elif cmd_type == "release_quarantine":
        if journal is None or quarantine_store is None or executed_commands is None:
            log.error("commands.dispatch.release_missing_dependency")
            return
        await handle_release_quarantine(
            command=command,
            baseline_engine=baseline_engine,
            state=state,
            journal=journal,
            quarantine_store=quarantine_store,
            registry=executed_commands,
            valkey_client=valkey_client,
            config=config,
        )
    elif cmd_type == "update_config":
        await handle_update_config(
            command=command,
            detector=detector,
            baseline_engine=baseline_engine,
            state=state,
            valkey_client=valkey_client,
            config=config,
            preflight_registry=preflight_registry,
        )
    elif cmd_type == "rescan_baseline":
        await handle_rescan_baseline(
            command=command,
            baseline_engine=baseline_engine,
            state=state,
            valkey_client=valkey_client,
            config=config,
        )
    else:
        # 4. Tipo desconocido: log warning, sin excepción
        log.warning("commands.dispatch.unknown_type", cmd_type=cmd_type)


def _load_shared_secret(config: "AgentConfig") -> bytes | None:
    """Carga el shared_secret desde el directorio de secrets del agente."""
    try:
        from agent.streams import load_shared_secret
        return load_shared_secret(config.storage.secrets_dir)
    except (FileNotFoundError, OSError) as exc:
        log.error("commands.load_shared_secret.failed", error=str(exc))
        return None


def _path_is_within_watch_paths(path: str, watch_paths: list[str]) -> bool:
    """Return whether ``path`` resolves inside a configured watch root.

    Both sides are canonicalized before component-aware containment.  A string
    prefix check is insufficient here: ``/srv/watch-escape`` starts with
    ``/srv/watch`` but is a sibling, not a child.  Resolving the candidate also
    prevents ``..`` and symlink traversal from escaping the authorized roots.
    """
    candidate = Path(os.path.realpath(path))
    roots = (Path(os.path.realpath(root)) for root in watch_paths)
    return any(candidate.is_relative_to(root) for root in roots)


# ── Handler: baseline_update ──────────────────────────────────────────────────


async def handle_baseline_update(
    command: dict[str, Any],
    baseline_engine: "BaselineEngine",
    state: "AgentState",
    valkey_client: "avalkey.Valkey",
    config: "AgentConfig",
) -> None:
    """
    Actualiza el baseline local cifrado a partir del comando baseline_update.

    1. Verifica que ruleset_version >= state.ruleset_version.
    2. Llama BaselineEngine.update_from_command().
    3. Actualiza state.ruleset_version y persiste.
    4. Publica event_ack.
    """
    from agent.state import save_state

    command_id = command.get("command_id", "")
    event_id = command.get("event_id")
    cmd_version = command.get("ruleset_version", 0)

    # 2. Verificar versión
    if cmd_version < state.ruleset_version:
        log.debug(
            "commands.baseline_update.stale_version",
            cmd_version=cmd_version,
            local_version=state.ruleset_version,
        )
        return

    path = command.get("path", "")
    hash_value: str | None = command.get("hash")
    baseline_status = command.get("baseline_status", "present")
    source_event_id = command.get("source_event_id")

    try:
        baseline_engine.update_from_command(
            path, hash_value, baseline_status, source_event_id=source_event_id,
        )
    except Exception as exc:
        log.error("commands.baseline_update.write_failed", path=path, error=str(exc))
        await _publish_ack(
            valkey_client, command_id, "baseline_update", event_id, config,
            ok=False, error=str(exc),
        )
        return

    # 3. Actualizar state.ruleset_version
    state.ruleset_version = cmd_version
    try:
        save_state(state)
    except Exception as exc:
        log.warning("commands.baseline_update.save_state_failed", error=str(exc))

    log.info(
        "commands.baseline_update.done",
        path=path,
        ruleset_version=cmd_version,
    )

    # 4. Publicar event_ack
    await _publish_ack(
        valkey_client, command_id, "baseline_update", event_id, config, ok=True,
    )


# ── Handler: restore_file ─────────────────────────────────────────────────────


async def handle_restore_file(
    command: dict[str, Any],
    baseline_engine: "BaselineEngine",
    journal: "JournalManager",
    valkey_client: "avalkey.Valkey",
    config: "AgentConfig",
) -> None:
    """
    Restaura un archivo desde el baseline local con journal transaccional.

    1. Journal pre-acción (pending).
    2. Restaurar archivo usando lógica de decision.py (_auto_restore equivalente).
    3. Journal post-acción (completed/failed).
    4. Publicar event_ack.
    """
    command_id = command.get("command_id", "")
    event_id = command.get("event_id")
    path = command.get("path", "")

    # D18 / RN-116: validate path containment within watch_paths
    if not config.watch_paths:
        log.error("commands.path_outside_watch.no_watch_paths", path=path)
        await _publish_ack(
            valkey_client, command_id, "restore_file", event_id, config,
            ok=False, error="no_watch_paths_configured",
        )
        return
    if not _path_is_within_watch_paths(path, config.watch_paths):
        log.warning("commands.path_outside_watch", path=path)
        await _publish_ack(
            valkey_client, command_id, "restore_file", event_id, config,
            ok=False, error="path_outside_watch_paths",
        )
        return

    # Usar command_id como event_id del journal para unicidad
    journal_key = command_id or str(uuid.uuid4())

    # 1. Journal pre-acción
    journal.write_pending(journal_key, path, "restore")

    # 2. Restaurar (D36/RN-130: mismo camino de escritura que
    # DecisionEngine._auto_restore en agent/decision.py, duplicado porque la
    # razón ya llegaba al backend por otro canal — el ack — y ahora habla el
    # mismo vocabulario cerrado). La ESCRITURA sigue duplicada; la
    # VERIFICACIÓN es compartida: `verify_restored_file` (D81/RN-175).)
    error_reason: str | None = None
    was_quarantined = False
    try:
        from agent.baseline import select_restorable_content
        from agent.decision import (
            action_error_from_oserror,
            parse_baseline_mode,
            verify_restored_file,
        )

        entry = baseline_engine.read_entry(path)
        if entry is None:
            raise ValueError("no_baseline_content")
        was_quarantined = entry.status == "quarantined"

        result = select_restorable_content(entry)
        if result is None:
            raise ValueError("no_restorable_content")

        content, expected_hash = result

        # D-6: metadata ausente => la restauración falla, nunca a medias.
        mode = parse_baseline_mode(entry.mode)
        uid = entry.uid
        gid = entry.gid
        if mode is None or uid is None or gid is None:
            raise ValueError("no_baseline_metadata")

        tmp_path = path + ".fim_restore_tmp"

        # O_EXCL: un tmp huérfano hace fallar el intento en vez de reusarlo.
        try:
            fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        except OSError as exc:
            raise ValueError(action_error_from_oserror(exc, fallback="write_failed")) from exc

        try:
            os.write(fd, content)
            os.fsync(fd)
            # D-6: fchown ANTES que fchmod — chown(2) limpia setuid/setgid.
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
        except OSError as exc:
            os.close(fd)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise ValueError(action_error_from_oserror(exc, fallback="write_failed")) from exc
        else:
            os.close(fd)

        try:
            os.replace(tmp_path, path)
        except OSError as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise ValueError(action_error_from_oserror(exc, fallback="write_failed")) from exc

        err = verify_restored_file(path, content, expected_hash)
        if err is not None:
            raise ValueError(err)

        # D82/RN-176 exit (a): a verified restore returns a quarantined entry to
        # "present" without re-reading metadata from disk. Reached only after
        # the disk verification above succeeded; any failure leaves it untouched.
        if was_quarantined:
            try:
                baseline_engine.clear_quarantine(path)
            except Exception as clear_exc:
                # The restore itself succeeded. The identical-hash echo of the
                # os.replace clears the state in the detector (D-10).
                log.error(
                    "commands.restore_file.clear_quarantine_failed",
                    path=path,
                    error_type=type(clear_exc).__name__,
                )

        log.info("commands.restore_file.done", path=path, command_id=command_id)
        journal.mark_completed(journal_key)

    except Exception as exc:
        error_reason = str(exc)
        log.error("commands.restore_file.failed", path=path, error=error_reason)
        journal.mark_failed(journal_key, error_reason)

    # 4. Publicar event_ack
    await _publish_ack(
        valkey_client, command_id, "restore_file", event_id, config,
        ok=error_reason is None, error=error_reason,
    )


# ── Handler: quarantine_file ──────────────────────────────────────────────────


async def handle_quarantine_file(
    command: dict[str, Any],
    journal: "JournalManager",
    valkey_client: "avalkey.Valkey",
    config: "AgentConfig",
    baseline_engine: "BaselineEngine",
    quarantine_dir: str | None = None,
    quarantine_store: "QuarantineStore | None" = None,
) -> None:
    """
    Pone un archivo en cuarentena con journal transaccional (D82/RN-176).

    Usa la implementación única `quarantine_and_record` (la misma que el
    `DecisionEngine`; cierra el residual 9): journal pending -> artefacto cifrado
    y retiro del origen -> entrada de baseline `quarantined` que conserva la
    versión aprobada. La identidad de acción y la clave de journal son el
    `agent_event_id` del comando (el `event_id` UUID del agente), nunca el
    `command_id`. Sin él: `quarantine_identity_missing`, sin journal ni acción.
    El handler cierra el journal (completed/failed) y después publica event_ack.
    """
    command_id = command.get("command_id", "")
    event_id = command.get("event_id")
    path = command.get("path", "")

    # D18 / RN-116: validate path containment within watch_paths
    if not config.watch_paths:
        log.error("commands.path_outside_watch.no_watch_paths", path=path)
        await _publish_ack(
            valkey_client, command_id, "quarantine_file", event_id, config,
            ok=False, error="no_watch_paths_configured",
        )
        return
    if not _path_is_within_watch_paths(path, config.watch_paths):
        log.warning("commands.path_outside_watch", path=path)
        await _publish_ack(
            valkey_client, command_id, "quarantine_file", event_id, config,
            ok=False, error="path_outside_watch_paths",
        )
        return

    # D82/RN-176: the artifact identity is the agent's event_id, shared with the
    # automatic path; falling back to command_id would orphan the artifact.
    agent_event_id = command.get("agent_event_id")
    if not isinstance(agent_event_id, str) or not agent_event_id:
        log.error("commands.quarantine_file.identity_missing", command_id=command_id)
        await _publish_ack(
            valkey_client, command_id, "quarantine_file", event_id, config,
            ok=False, error="quarantine_identity_missing",
        )
        return
    journal_key = agent_event_id

    error_reason: str | None = None
    try:
        if quarantine_store is None:
            from agent.baseline import load_master_secret
            from agent.quarantine import QuarantineStore

            _qdir = Path(quarantine_dir) if quarantine_dir else Path("/var/lib/fim-agent/quarantine")
            quarantine_store = QuarantineStore(
                _qdir,
                load_master_secret(config.storage.secrets_dir),
                config.agent_id,
            )
    except Exception as exc:
        # Resource acquisition, not quarantine: a missing master secret or an
        # unusable directory both mean there is no usable store.
        error_reason = "quarantine_store_unavailable"
        log.error(
            "commands.quarantine_file.store_unavailable",
            path=path,
            error_type=type(exc).__name__,
        )
        journal.ensure_pending(journal_key, path, "quarantine")
        journal.mark_failed(journal_key, error_reason)
    else:
        from agent.quarantine import quarantine_and_record

        outcome = quarantine_and_record(
            store=quarantine_store,
            baseline=baseline_engine,
            journal=journal,
            action_id=journal_key,
            path=path,
        )
        if outcome.error is None:
            assert outcome.artifact is not None
            log.info(
                "commands.quarantine_file.done",
                path=path,
                dest=str(outcome.artifact.path),
            )
            journal.mark_completed(journal_key)
        else:
            error_reason = outcome.error
            log.error("commands.quarantine_file.failed", path=path, error=error_reason)
            journal.mark_failed(journal_key, error_reason)

    # Publicar event_ack
    await _publish_ack(
        valkey_client, command_id, "quarantine_file", event_id, config,
        ok=error_reason is None, error=error_reason,
    )


# ── Handler: release_quarantine (D83/RN-177) ──────────────────────────────────

_RELEASE_MODES = ("restore_original", "restore_baseline", "discard")
_SETID_BITS = stat.S_ISUID | stat.S_ISGID


class _ReleaseError(Exception):
    """A release step failed with a closed-vocabulary code (RN-71, D36/RN-130)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fsync_dir(directory: str) -> None:
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_without_overwrite(
    path: str, content: bytes, *, mode: int, uid: int, gid: int
) -> None:
    """Relocate ``content`` to ``path`` and NEVER replace an existing destination.

    D83/RN-177 (D-5): the bytes go to ``<path>.fim_restore_tmp`` (``O_EXCL``,
    ``fchown`` before ``fchmod`` per D36/RN-130) and are published with
    ``link(2)``, which fails atomically with ``EEXIST`` when something already
    occupies the path: no TOCTOU window, unlike ``os.replace``. The temporary is
    always unlinked. The detector drops events on the ``.fim_restore_tmp`` suffix.
    """
    from agent.decision import action_error_from_oserror

    tmp_path = path + ".fim_restore_tmp"
    try:
        fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    except OSError as exc:
        raise _ReleaseError(action_error_from_oserror(exc, fallback="write_failed")) from exc

    try:
        try:
            view = memoryview(content)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
            os.fchown(fd, uid, gid)
            os.fchmod(fd, mode)
        except OSError as exc:
            raise _ReleaseError(
                action_error_from_oserror(exc, fallback="write_failed")
            ) from exc
        finally:
            os.close(fd)

        try:
            os.link(tmp_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise _ReleaseError("path_occupied") from exc
        except OSError as exc:
            raise _ReleaseError(
                action_error_from_oserror(exc, fallback="write_failed")
            ) from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    try:
        _fsync_dir(os.path.dirname(path) or ".")
    except OSError as exc:
        log.warning("commands.release_quarantine.fsync_dir_failed", errno=exc.errno)


def _require_path_free(path: str) -> None:
    """Early ``path_occupied``; the ``link(2)`` in the publication is the real guard."""
    from agent.decision import action_error_from_oserror

    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise _ReleaseError(action_error_from_oserror(exc, fallback="write_failed")) from exc
    raise _ReleaseError("path_occupied")


def _disk_hash(path: str) -> str | None:
    """SHA-256 of the regular file at ``path`` without following symlinks, or None."""
    digest = hashlib.sha256()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            while block := os.read(fd, 1024 * 1024):
                digest.update(block)
        finally:
            os.close(fd)
    except OSError:
        return None
    return digest.hexdigest()


def _release_already_applied(
    baseline_engine: "BaselineEngine", path: str, target_hash: str | None
) -> bool:
    """D-9: did a previous run already finish the relocation before a crash?

    True when the path holds the target content and the baseline entry is
    ``present`` with that same hash. ``target_hash`` is ``None`` for
    ``restore_baseline``, where the target is the entry's own approved hash.
    """
    try:
        entry = baseline_engine.read_entry(path)
    except Exception:
        return False
    if entry is None or entry.status != "present" or not entry.hash:
        return False
    if target_hash is not None and entry.hash != target_hash:
        return False
    return _disk_hash(path) == entry.hash


def _release_restore_original(
    *,
    command: dict[str, Any],
    path: str,
    agent_event_id: str,
    expected_sha256: str,
    baseline_engine: "BaselineEngine",
    state: "AgentState",
    quarantine_store: "QuarantineStore",
) -> None:
    from agent.decision import verify_restored_file
    from agent.quarantine import QuarantineError
    from agent.state import save_state

    cmd_version = command.get("ruleset_version")
    if not isinstance(cmd_version, int) or isinstance(cmd_version, bool):
        raise _ReleaseError("invalid_release_command")
    # Same guard as baseline_update; here the stale case is acked so the operator
    # sees it without waiting for the timeout sweep.
    if cmd_version < state.ruleset_version:
        raise _ReleaseError("stale_ruleset_version")

    try:
        artifact = quarantine_store.load_for_release(agent_event_id, path, expected_sha256)
    except QuarantineError as exc:
        if exc.reason == "artifact_not_found" and _release_already_applied(
            baseline_engine, path, expected_sha256
        ):
            # Crash between remove_artifact and the registry write (D-9).
            state.ruleset_version = max(state.ruleset_version, cmd_version)
            try:
                save_state(state)
            except Exception as save_exc:
                log.warning(
                    "commands.release_quarantine.save_state_failed",
                    error_type=type(save_exc).__name__,
                )
            return
        raise _ReleaseError(exc.reason) from exc

    meta = artifact.metadata
    if meta.get("kind") == "symlink":
        raise _ReleaseError("unsupported_file_type")
    uid, gid, raw_mode = meta.get("uid"), meta.get("gid"), meta.get("mode")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (uid, gid, raw_mode)):
        raise _ReleaseError("no_artifact_metadata")
    # setuid/setgid never survive an approval-by-release (D83/RN-177).
    mode = raw_mode & ~_SETID_BITS

    _require_path_free(path)

    # D83: adopt BEFORE relocating, so the FAN_CREATE of the link already matches
    # the baseline and is dropped by the identical-hash rule (detector D-10).
    previous = baseline_engine.read_entry(path)
    baseline_engine.adopt_content(path, artifact.content, mode=mode, uid=uid, gid=gid)
    try:
        _publish_without_overwrite(path, artifact.content, mode=mode, uid=uid, gid=gid)
        err = verify_restored_file(path, artifact.content, expected_sha256)
        if err is not None:
            raise _ReleaseError(err)
        try:
            quarantine_store.remove_artifact(agent_event_id, path, expected_sha256)
        except QuarantineError as exc:
            raise _ReleaseError(exc.reason) from exc
    except _ReleaseError:
        _undo_adoption(baseline_engine, path, previous, agent_event_id)
        raise

    state.ruleset_version = cmd_version
    try:
        save_state(state)
    except Exception as exc:
        log.warning(
            "commands.release_quarantine.save_state_failed", error_type=type(exc).__name__
        )


def _undo_adoption(
    baseline_engine: "BaselineEngine",
    path: str,
    previous: "BaselineEntry | None",
    agent_event_id: str,
) -> None:
    """Return the baseline entry to its pre-release (``quarantined``) shape."""
    try:
        if previous is not None:
            baseline_engine.write_entry_object(previous)
        else:
            baseline_engine.mark_quarantined(path, agent_event_id)
    except Exception as exc:
        log.error(
            "commands.release_quarantine.baseline_undo_failed",
            error_type=type(exc).__name__,
        )


def _release_restore_baseline(
    *,
    path: str,
    agent_event_id: str,
    expected_sha256: str,
    baseline_engine: "BaselineEngine",
    quarantine_store: "QuarantineStore",
) -> None:
    from agent.baseline import select_restorable_content
    from agent.decision import parse_baseline_mode, verify_restored_file
    from agent.quarantine import QuarantineError

    try:
        quarantine_store.load_for_release(
            agent_event_id, path, expected_sha256, include_content=False
        )
    except QuarantineError as exc:
        if exc.reason == "artifact_not_found" and _release_already_applied(
            baseline_engine, path, None
        ):
            return
        raise _ReleaseError(exc.reason) from exc

    _require_path_free(path)

    entry = baseline_engine.read_entry(path)
    result = select_restorable_content(entry) if entry is not None else None
    if entry is None or result is None:
        raise _ReleaseError("no_restorable_content")
    content, expected_hash = result

    mode = parse_baseline_mode(entry.mode)
    uid, gid = entry.uid, entry.gid
    if mode is None or uid is None or gid is None:
        raise _ReleaseError("no_baseline_metadata")

    _publish_without_overwrite(path, content, mode=mode, uid=uid, gid=gid)
    err = verify_restored_file(path, content, expected_hash)
    if err is not None:
        raise _ReleaseError(err)

    # D82/RN-176 exit (a): a verified restore returns the entry to "present".
    baseline_engine.clear_quarantine(path)
    try:
        quarantine_store.remove_artifact(agent_event_id, path, expected_sha256)
    except QuarantineError as exc:
        _undo_adoption(baseline_engine, path, entry, agent_event_id)
        raise _ReleaseError(exc.reason) from exc


def _release_discard(
    *,
    path: str,
    agent_event_id: str,
    expected_sha256: str,
    quarantine_store: "QuarantineStore",
) -> None:
    from agent.quarantine import QuarantineError

    try:
        quarantine_store.load_for_release(
            agent_event_id, path, expected_sha256, include_content=False
        )
        quarantine_store.remove_artifact(agent_event_id, path, expected_sha256)
    except QuarantineError as exc:
        raise _ReleaseError(exc.reason) from exc


async def handle_release_quarantine(
    command: dict[str, Any],
    *,
    baseline_engine: "BaselineEngine",
    state: "AgentState",
    journal: "JournalManager",
    quarantine_store: "QuarantineStore",
    registry: "ExecutedCommandRegistry",
    valkey_client: "avalkey.Valkey",
    config: "AgentConfig",
) -> None:
    """
    Libera una cuarentena vigente (D83/RN-177): tres modos, siempre tras
    autenticar el artefacto (`QuarantineStore.load_for_release`).

    - restore_original: equivale a APROBAR. Adopta el baseline antes de reubicar,
      reubica sin sobrescribir (`path_occupied`), quita setuid/setgid, verifica
      desde disco (D81/RN-175), elimina el artefacto y avanza
      `state.ruleset_version` con la guarda de obsolescencia.
    - restore_baseline: restaura la versión aprobada del baseline, sin
      sobrescribir, y elimina el artefacto.
    - discard: sólo elimina el artefacto autenticado.

    Idempotencia por `command_id`: journal `pending` antes del primer efecto,
    registro durable ANTES del ack; una re-entrega re-publica el mismo ack sin
    repetir efectos. Ni los logs ni el ack llevan contenido de archivo.
    """
    command_id = command.get("command_id", "")
    event_id = command.get("event_id")
    path = command.get("path", "")
    mode = command.get("mode")
    agent_event_id = command.get("agent_event_id")
    expected_sha256 = command.get("expected_sha256")

    if not isinstance(command_id, str) or not command_id:
        log.error("commands.release_quarantine.command_id_missing")
        return

    recorded = registry.get(command_id)
    if recorded is not None:
        log.info("commands.release_quarantine.redelivered", command_id=command_id)
        await _publish_ack(
            valkey_client, command_id, "release_quarantine", event_id, config,
            ok=bool(recorded.get("ok")), error=recorded.get("error"),
        )
        return

    async def _close(error: str | None) -> None:
        if error is None:
            journal.mark_completed(command_id)
            log.info(
                "commands.release_quarantine.done",
                mode=mode, command_id=command_id, event_id=event_id,
            )
        else:
            journal.mark_failed(command_id, error)
            log.error(
                "commands.release_quarantine.failed",
                mode=mode, command_id=command_id, event_id=event_id, error=error,
            )
        registry.record(command_id, "release_quarantine", error is None, error)
        await _publish_ack(
            valkey_client, command_id, "release_quarantine", event_id, config,
            ok=error is None, error=error,
        )

    if (
        mode not in _RELEASE_MODES
        or not isinstance(path, str)
        or not path
        or not isinstance(agent_event_id, str)
        or not agent_event_id
        or not isinstance(expected_sha256, str)
    ):
        await _close("invalid_release_command")
        return

    # D18 / RN-116: validate path containment within watch_paths
    if not config.watch_paths:
        await _close("no_watch_paths_configured")
        return
    if not _path_is_within_watch_paths(path, config.watch_paths):
        await _close("path_outside_watch_paths")
        return

    journal.write_pending(command_id, path, "release_quarantine")

    error_reason: str | None = None
    try:
        if mode == "restore_original":
            _release_restore_original(
                command=command, path=path, agent_event_id=agent_event_id,
                expected_sha256=expected_sha256, baseline_engine=baseline_engine,
                state=state, quarantine_store=quarantine_store,
            )
        elif mode == "restore_baseline":
            _release_restore_baseline(
                path=path, agent_event_id=agent_event_id,
                expected_sha256=expected_sha256, baseline_engine=baseline_engine,
                quarantine_store=quarantine_store,
            )
        else:
            _release_discard(
                path=path, agent_event_id=agent_event_id,
                expected_sha256=expected_sha256, quarantine_store=quarantine_store,
            )
    except _ReleaseError as exc:
        error_reason = exc.code
    except Exception as exc:
        log.error(
            "commands.release_quarantine.unexpected",
            command_id=command_id, error_type=type(exc).__name__,
        )
        error_reason = "release_failed"

    await _close(error_reason)


# ── Handler: update_config (C14) ──────────────────────────────────────────────


async def handle_update_config(
    command: dict[str, Any],
    detector: "FanotifyDetector | None",
    baseline_engine: "BaselineEngine",
    state: "AgentState",
    valkey_client: "avalkey.Valkey",
    config: "AgentConfig",
    preflight_registry: "PreflightRegistry | None" = None,
) -> None:
    """
    Actualiza la configuración de watch_paths del agente (C14, D-C14-06/07).

    1. Calcula paths añadidos/eliminados respecto a la config actual.
    2. Llama detector.reload_watch_paths(new_paths) para actualizar fanotify.
    3. Llama baseline_engine.run_scan(added_paths) solo para paths nuevos.
    3.5. Reejecuta el preflight sobre el conjunto nuevo (D36/RN-130): hace
         visible la limitación conocida de D36 — un path agregado en caliente
         queda monitoreado pero no remediable hasta regenerar el drop-in.
    4. Actualiza config.yaml local con los nuevos watch_paths. El fallo de
       persistencia deja de tragarse en silencio: se loguea a error y se
       refleja en el registry para que el heartbeat lo reporte (D36/RN-130).
    5. Actualiza state.ruleset_version y persiste en state.json.
    6. Publica event_ack — el `ok` no cambia por un fallo de persistencia:
       la recarga en caliente sí ocurrió (D-9 del design). El canal para
       "corriendo pero degradado" es el heartbeat, no el ack.
    """
    import yaml

    from agent.state import save_state

    command_id = command.get("command_id", "")
    event_id = command.get("event_id")
    new_paths: list[str] = command.get("watch_paths") or []
    cmd_version: int = command.get("ruleset_version", 0)

    # Monotonic version guard — mirrors handle_baseline_update (BUG-12)
    if cmd_version < state.ruleset_version:
        log.debug(
            "commands.update_config.stale_version",
            cmd_version=cmd_version,
            local_version=state.ruleset_version,
        )
        return

    error_reason: str | None = None
    try:
        current_watch_paths = list(config.watch_paths)
        current_set = set(current_watch_paths)
        new_set = set(new_paths)

        added_paths = list(new_set - current_set)
        removed_paths = list(current_set - new_set)

        log.info(
            "commands.update_config.paths_delta",
            added=added_paths,
            removed=removed_paths,
        )

        # Recargar fanotify
        if detector is not None:
            detector.reload_watch_paths(new_paths)
        else:
            log.warning("commands.update_config.no_detector")

        # Scan solo paths nuevos
        if added_paths:
            baseline_engine.run_scan(added_paths)
            # D80/RN-174: a root scanned here has completed its first scan. Persisted
            # by the save_state below, together with the removals.
            scanned_roots = [p for p in added_paths if Path(p).exists()]
            state.initialized_roots = sorted(set(state.initialized_roots) | set(scanned_roots))
        if removed_paths:
            state.initialized_roots = sorted(set(state.initialized_roots) - set(removed_paths))

        # D36/RN-130: reejecutar el preflight sobre el conjunto nuevo. No
        # bloquea el reload — es la vista de reporte, no un gate (D-7/D-9).
        if preflight_registry is not None:
            from agent.preflight import run_preflight

            preflight_registry.update(run_preflight(new_paths))

        # Actualizar config.yaml local
        config_path = config._config_path or Path("/etc/fim-agent/config.yaml")
        config_persisted = False
        try:
            import os as _os
            if _os.path.exists(str(config_path)):
                with open(str(config_path)) as f:
                    raw_config = yaml.safe_load(f) or {}
                raw_config["watch_paths"] = new_paths
                tmp_path = str(config_path) + ".tmp"
                with open(tmp_path, "w") as f:
                    yaml.dump(raw_config, f, default_flow_style=False)
                _os.replace(tmp_path, str(config_path))
                config_persisted = True
                log.info("commands.update_config.config_yaml_updated", path=str(config_path))
            else:
                # Antes era un no-op sin ni siquiera un warning (:517).
                log.error("commands.update_config.config_yaml_missing", path=str(config_path))
        except Exception as exc:
            # Antes era log.warning y el ack seguía reportando ok=true
            # mientras la config persistida divergía del runtime en
            # silencio (:526-527). El `ok` del ack sigue sin cambiar
            # (D-9) — el canal correcto es el heartbeat.
            log.error("commands.update_config.config_yaml_write_failed", error=str(exc))

        if preflight_registry is not None:
            preflight_registry.set_config_persisted(config_persisted)

        # Actualizar watch_paths en el objeto config en memoria
        config.watch_paths = new_paths  # type: ignore[assignment]

        # Actualizar state.ruleset_version
        state.ruleset_version = cmd_version
        try:
            save_state(state)
        except Exception as exc:
            log.warning("commands.update_config.save_state_failed", error=str(exc))

        log.info(
            "commands.update_config.done",
            new_paths=new_paths,
            ruleset_version=cmd_version,
        )

    except Exception as exc:
        error_reason = str(exc)
        log.error("commands.update_config.failed", error=error_reason)

    # D36/RN-130 (D-9): `ok` NO se condiciona a config_persisted. Un fallo al
    # persistir config.yaml no entra en error_reason — la recarga en caliente
    # sí ocurrió (detector recargado, paths escaneados, config en memoria
    # actualizada) y el contrato de event_ack ya está asentado (C36). El
    # canal para "corriendo pero degradado" es el heartbeat (config_persisted
    # en el registry), no el ack. NO "arreglar" esto acoplando persist a ok.
    await _publish_ack(
        valkey_client, command_id, "update_config", event_id, config,
        ok=error_reason is None, error=error_reason,
    )


# ── Handler: rescan_baseline (C14) ────────────────────────────────────────────


async def handle_rescan_baseline(
    command: dict[str, Any],
    baseline_engine: "BaselineEngine",
    state: "AgentState",
    valkey_client: "avalkey.Valkey",
    config: "AgentConfig",
) -> None:
    """
    Ejecuta scan de baseline sobre watch_paths — completo, o acotado a `paths`
    específicos si el comando los trae (US-22, C11).

    1. Guard de versión monotónico (mismo patrón que handle_update_config,
       BUG-12): un comando con ruleset_version menor al local se descarta sin
       ack (comando repetido o fuera de orden).
    2. Si el comando trae `paths`, se acotan a los watch_paths configurados
       (misma validación de contención que el dispatcher usa para
       restore_file/quarantine_file — _path_is_within_watch_paths); un path
       fuera de los watch roots se descarta con log warning en vez de abortar
       todo el rescan. Sin `paths` (o vacío): comportamiento previo, scan
       completo de todos los watch_paths.
    3. Llama baseline_engine.run_scan(paths) para el scan.
    4. Actualiza state.ruleset_version y persiste en state.json (mismo patrón
       que handle_update_config) — solo tras un scan exitoso.
    5. Publica event_ack con resultado.
    """
    from agent.state import save_state

    command_id = command.get("command_id", "")
    event_id = command.get("event_id")
    cmd_version: int = command.get("ruleset_version", 0)

    # Monotonic version guard — mirrors handle_update_config (BUG-12, US-22/C11)
    if cmd_version < state.ruleset_version:
        log.debug(
            "commands.rescan_baseline.stale_version",
            cmd_version=cmd_version,
            local_version=state.ruleset_version,
        )
        return

    error_reason: str | None = None
    try:
        requested_paths: list[str] = command.get("paths") or []
        if requested_paths:
            watch_paths = list(config.watch_paths)
            scan_paths = [
                p for p in requested_paths if _path_is_within_watch_paths(p, watch_paths)
            ]
            skipped = [p for p in requested_paths if p not in scan_paths]
            if skipped:
                log.warning(
                    "commands.rescan_baseline.paths_outside_watch_roots",
                    skipped=skipped,
                )
        else:
            scan_paths = list(config.watch_paths)

        log.info("commands.rescan_baseline.starting", paths=scan_paths)

        baseline_engine.run_scan(scan_paths)

        state.ruleset_version = cmd_version
        try:
            save_state(state)
        except Exception as exc:
            log.warning("commands.rescan_baseline.save_state_failed", error=str(exc))

        log.info("commands.rescan_baseline.done", paths=scan_paths)

    except Exception as exc:
        error_reason = str(exc)
        log.error("commands.rescan_baseline.failed", error=error_reason)

    await _publish_ack(
        valkey_client, command_id, "rescan_baseline", event_id, config,
        ok=error_reason is None, error=error_reason,
    )
