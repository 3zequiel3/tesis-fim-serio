"""
Lógica de negocio para aprobación y rechazo de eventos FIM (C13).

Expone: _approve_single, _reject_single, approve_bulk, reject_bulk.

Orden de operaciones en approve (FIX-02):
  1. Verificar confirm_absent si hash is None (antes del UPDATE).
  2. UPDATE optimista sobre events (status, version, resolved_at, resolved_by).
  3. flush + refresh.
  4. increment_ruleset_version.
  5. Upsert en baseline_entries.
  6. Escribir audit_log.
  7. commit.
  8. refresh.
  9. Publicar baseline_update en Valkey (post-commit).

Orden de operaciones en reject (FIX-02):
  1. UPDATE optimista sobre events.
  2. flush + refresh.
  3. Consultar baseline_entry.
  4. Escribir audit_log.
  5. commit.
  6. refresh.
  7. Publicar restore_file o quarantine_file post-commit (no-op si baseline absent).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from app.modules.agents.models import Agent, BaselineEntry, BaselineStatus
from app.modules.audit.models import AuditLog
from app.modules.events.models import Event, EventStatus
from app.modules.rules.service import increment_ruleset_version as _increment_ruleset_version
from app.modules.actions.schemas import RejectAction

log = structlog.get_logger()


# ── Excepciones de dominio ────────────────────────────────────────────────────


class ConflictError(Exception):
    """El UPDATE optimista no afectó ninguna fila (versión incorrecta o evento no-pending)."""
    def __init__(self, event_id: int) -> None:
        self.event_id = event_id
        super().__init__(f"conflict on event {event_id}")


class AbsentConfirmationRequired(Exception):
    """El evento tiene hash=None y confirm_absent no fue True."""
    def __init__(self, event_id: int) -> None:
        self.event_id = event_id
        super().__init__(f"absent_confirmation_required for event {event_id}")


# ── Helpers internos ──────────────────────────────────────────────────────────
#
# El incremento de RulesetVersion (M6) está unificado en
# `rules.service.increment_ruleset_version` (UPDATE ... RETURNING atómico) y
# se reutiliza acá bajo el alias `_increment_ruleset_version` para no tocar
# los call-sites de approve/reject. No debe reimplementarse localmente.


def _get_event(session: Session, event_id: int) -> Event | None:
    return session.exec(select(Event).where(Event.id == event_id)).first()


def _get_agent(session: Session, agent_id: str) -> Agent | None:
    return session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()


def _get_baseline_entry(session: Session, path: str, agent_id: str) -> BaselineEntry | None:
    return session.exec(
        select(BaselineEntry).where(
            BaselineEntry.path == path,
            BaselineEntry.agent_id == agent_id,
        )
    ).first()


def _upsert_baseline_entry(
    session: Session,
    path: str,
    agent_id: str,
    hash_value: str | None,
    baseline_status: BaselineStatus,
    ruleset_version: int,
) -> None:
    entry = _get_baseline_entry(session, path, agent_id)
    if entry is None:
        entry = BaselineEntry(
            path=path,
            agent_id=agent_id,
            hash=hash_value,
            status=baseline_status,
            last_updated=datetime.now(timezone.utc),
            ruleset_version=ruleset_version,
        )
        session.add(entry)
    else:
        entry.hash = hash_value
        entry.status = baseline_status
        entry.last_updated = datetime.now(timezone.utc)
        entry.ruleset_version = ruleset_version
        session.add(entry)


def _write_audit(
    session: Session,
    user_id: int,
    action: str,
    event_id: int,
    details: dict[str, Any] | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        target_type="event",
        target_id=event_id,
        detail=json.dumps(details) if details else None,
    )
    session.add(entry)


# ── Approve single ────────────────────────────────────────────────────────────


def _approve_single(
    db: Session,
    valkey_client: Any,
    event_id: int,
    version: int,
    confirm_absent: bool,
    user_id: int,
) -> Event:
    """
    Aprueba un evento pending con optimistic locking.

    Raises:
        AbsentConfirmationRequired: si hash is None y confirm_absent is False.
        ConflictError: si el UPDATE no afecta ninguna fila.
    """
    from app.modules.actions.streams import publish_baseline_update

    # 1. Leer el evento para detectar hash None ANTES del UPDATE (no modifica estado)
    # En el modelo Event, hash_detected es str; cadena vacía "" indica archivo ausente (D-C13-04).
    event = _get_event(db, event_id)
    if event is None:
        raise ConflictError(event_id)

    # Verificar ausencia antes del UPDATE (D-C13-04)
    # hash vacío o None = archivo eliminado/ausente
    hash_value: str | None = event.hash_detected if event.hash_detected else None
    if hash_value is None and not confirm_absent:
        raise AbsentConfirmationRequired(event_id)

    # 2. UPDATE optimista
    now = datetime.now(timezone.utc)
    stmt = (
        sa_update(Event)
        .where(
            Event.id == event_id,
            Event.version == version,
            Event.status == EventStatus.pending,
        )
        .values(
            status=EventStatus.approved,
            version=version + 1,
            resolved_at=now,
            resolved_by=user_id,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise ConflictError(event_id)

    # 3. Refrescar event para obtener datos actualizados
    db.flush()
    db.refresh(event)

    # 4. Incrementar ruleset_version
    new_version = _increment_ruleset_version(db)

    # 5. Upsert baseline_entries
    baseline_status = BaselineStatus.absent if hash_value is None else BaselineStatus.present
    _upsert_baseline_entry(db, event.path, event.agent_id, hash_value, baseline_status, new_version)

    # 6. Audit log
    _write_audit(db, user_id, "approve", event_id, {"version": version})

    # 7. Commit
    db.commit()

    # 8. Refresh post-commit
    db.refresh(event)

    # 9. Publicar baseline_update post-commit (FIX-02: el agente recibe el comando solo
    #    cuando la transacción ya es durable en Postgres)
    publish_baseline_update(db, valkey_client, event, new_version)

    log.info("service.actions.approve", event_id=event_id, user_id=user_id)
    return event


# ── Reject single ─────────────────────────────────────────────────────────────


def _reject_single(
    db: Session,
    valkey_client: Any,
    event_id: int,
    version: int,
    action: RejectAction,
    user_id: int,
) -> Event:
    """
    Rechaza un evento pending con optimistic locking.

    Raises:
        ConflictError: si el UPDATE no afecta ninguna fila.
    """
    from app.modules.actions.streams import publish_quarantine_file, publish_restore_file

    event = _get_event(db, event_id)
    if event is None:
        raise ConflictError(event_id)

    # 1. UPDATE optimista
    now = datetime.now(timezone.utc)
    stmt = (
        sa_update(Event)
        .where(
            Event.id == event_id,
            Event.version == version,
            Event.status == EventStatus.pending,
        )
        .values(
            status=EventStatus.rejected,
            version=version + 1,
            resolved_at=now,
            resolved_by=user_id,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    if result.rowcount == 0:
        raise ConflictError(event_id)

    # 2. flush + refresh
    db.flush()
    db.refresh(event)

    # 3. Consultar baseline_entry (dentro de la transacción, antes del commit)
    baseline_entry = _get_baseline_entry(db, event.path, event.agent_id)
    baseline_absent = baseline_entry is not None and baseline_entry.status == BaselineStatus.absent

    # 4. Audit log
    _write_audit(db, user_id, "reject", event_id, {"version": version, "action": action.value})

    # 5. Commit
    db.commit()

    # 6. Refresh post-commit
    db.refresh(event)

    # 7. Publicar comando post-commit (FIX-02: el agente recibe el comando solo
    #    cuando la transacción ya es durable en Postgres)
    if baseline_absent:
        log.warning(
            "service.actions.reject.baseline_absent_noop",
            event_id=event_id,
            path=event.path,
        )
    else:
        if action == RejectAction.restore:
            publish_restore_file(db, valkey_client, event)
        else:
            publish_quarantine_file(db, valkey_client, event)

    log.info("service.actions.reject", event_id=event_id, user_id=user_id, action=action.value)
    return event


# ── Bulk operations ───────────────────────────────────────────────────────────


def approve_bulk(
    db: Session,
    valkey_client: Any,
    items: list[dict[str, Any]],
    user_id: int,
) -> dict[str, Any]:
    """
    Aprueba múltiples eventos de forma independiente.
    Error en un ítem no aborta el resto.
    Retorna {"succeeded": [...], "failed": [...]}.
    """
    succeeded: list[int] = []
    failed: list[dict[str, Any]] = []

    for item in items:
        event_id = item["event_id"]
        try:
            _approve_single(
                db,
                valkey_client,
                event_id=event_id,
                version=item["version"],
                confirm_absent=item.get("confirm_absent", False),
                user_id=user_id,
            )
            succeeded.append(event_id)
        except AbsentConfirmationRequired:
            failed.append({"event_id": event_id, "reason": "absent_confirmation_required"})
        except ConflictError:
            failed.append({"event_id": event_id, "reason": "conflict"})
        except Exception as exc:
            log.error("service.actions.approve_bulk.unexpected", event_id=event_id, error=str(exc))
            failed.append({"event_id": event_id, "reason": "internal_error"})

    return {"succeeded": succeeded, "failed": failed}


def reject_bulk(
    db: Session,
    valkey_client: Any,
    items: list[dict[str, Any]],
    user_id: int,
) -> dict[str, Any]:
    """
    Rechaza múltiples eventos de forma independiente.
    Error en un ítem no aborta el resto.
    Retorna {"succeeded": [...], "failed": [...]}.
    """
    succeeded: list[int] = []
    failed: list[dict[str, Any]] = []

    for item in items:
        event_id = item["event_id"]
        try:
            action = RejectAction(item["action"])
            _reject_single(
                db,
                valkey_client,
                event_id=event_id,
                version=item["version"],
                action=action,
                user_id=user_id,
            )
            succeeded.append(event_id)
        except ConflictError:
            failed.append({"event_id": event_id, "reason": "conflict"})
        except Exception as exc:
            log.error("service.actions.reject_bulk.unexpected", event_id=event_id, error=str(exc))
            failed.append({"event_id": event_id, "reason": "internal_error"})

    return {"succeeded": succeeded, "failed": failed}
