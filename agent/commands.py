"""
Dispatcher de comandos entrantes del stream `commands` para el agente FIM (C13, C14).

Implementa:
  dispatch(command, *, baseline_engine, state, valkey_client, config, detector)
    — enruta por command["type"] con verificación HMAC y filtro target_agent_id.

Handlers:
  handle_baseline_update  — actualiza baseline local cifrado y publica event_ack.
  handle_restore_file     — restaura archivo desde baseline con journal.
  handle_quarantine_file  — pone en cuarentena con journal.
  handle_update_config    — recarga watch_paths en fanotify + scan de paths nuevos (C14).
  handle_rescan_baseline  — scan completo de todos los watch_paths (C14).

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
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from agent.streams import canonical_json, sign_payload, verify_payload

if TYPE_CHECKING:
    import valkey.asyncio as avalkey

    from agent.baseline import BaselineEngine
    from agent.config import AgentConfig
    from agent.detector import FanotifyDetector
    from agent.journal import JournalManager
    from agent.preflight import PreflightRegistry
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
    detector: "FanotifyDetector | None" = None,
    preflight_registry: "PreflightRegistry | None" = None,
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
            journal=journal,
            valkey_client=valkey_client,
            config=config,
            quarantine_dir=quarantine_dir,
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
    # mismo vocabulario cerrado)
    error_reason: str | None = None
    try:
        from agent.baseline import select_restorable_content
        from agent.decision import action_error_from_oserror, parse_baseline_mode

        entry = baseline_engine.read_entry(path)
        if entry is None:
            raise ValueError("no_baseline_content")

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

        restored_hash = hashlib.sha256(content).hexdigest()
        if expected_hash and restored_hash != expected_hash:
            raise ValueError("hash_mismatch_after_restore")

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
    quarantine_dir: str | None = None,
) -> None:
    """
    Pone un archivo en cuarentena con journal transaccional.

    1. Journal pre-acción (pending).
    2. Mover archivo a quarantine_dir con permisos 0400.
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

    journal_key = command_id or str(uuid.uuid4())

    # 1. Journal pre-acción
    journal.write_pending(journal_key, path, "quarantine")

    # 2. Quarantine
    error_reason: str | None = None
    try:
        _qdir = Path(quarantine_dir) if quarantine_dir else Path("/var/lib/fim-agent/quarantine")
        _qdir.mkdir(parents=True, exist_ok=True)

        basename = os.path.basename(path)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        dest = _qdir / f"{basename}.{timestamp}"

        if not os.path.exists(path):
            raise FileNotFoundError(f"file_not_found: {path}")

        shutil.move(path, str(dest))

        # Permisos 0400 en plataformas Unix
        try:
            os.chmod(str(dest), 0o400)
        except OSError as exc:
            log.warning("commands.quarantine_file.chmod_failed", dest=str(dest), error=str(exc))

        log.info("commands.quarantine_file.done", path=path, dest=str(dest))
        journal.mark_completed(journal_key)

    except FileNotFoundError:
        error_reason = "file_not_found"
        log.error("commands.quarantine_file.not_found", path=path)
        journal.mark_failed(journal_key, error_reason)
    except OSError as exc:
        from agent.decision import action_error_from_oserror

        error_reason = action_error_from_oserror(exc, fallback="move_failed")
        log.error("commands.quarantine_file.failed", path=path, error=error_reason)
        journal.mark_failed(journal_key, error_reason)
    except Exception as exc:
        error_reason = str(exc)
        log.error("commands.quarantine_file.failed", path=path, error=error_reason)
        journal.mark_failed(journal_key, error_reason)

    # 4. Publicar event_ack
    await _publish_ack(
        valkey_client, command_id, "quarantine_file", event_id, config,
        ok=error_reason is None, error=error_reason,
    )


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
    Ejecuta scan completo de baseline sobre todos los watch_paths actuales (C14, D-C14-07).

    1. Obtiene watch_paths actuales de config.
    2. Llama baseline_engine.run_scan(watch_paths) para scan completo.
    3. Publica event_ack con resultado.
    """
    command_id = command.get("command_id", "")
    event_id = command.get("event_id")

    error_reason: str | None = None
    try:
        watch_paths = list(config.watch_paths)
        log.info("commands.rescan_baseline.starting", watch_paths=watch_paths)

        baseline_engine.run_scan(watch_paths)

        log.info("commands.rescan_baseline.done", watch_paths=watch_paths)

    except Exception as exc:
        error_reason = str(exc)
        log.error("commands.rescan_baseline.failed", error=error_reason)

    await _publish_ack(
        valkey_client, command_id, "rescan_baseline", event_id, config,
        ok=error_reason is None, error=error_reason,
    )
