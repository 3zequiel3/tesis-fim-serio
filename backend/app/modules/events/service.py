"""
Lógica de negocio del dominio de eventos (Change 11).

Expone: validate_transition, ingest_event, compact_chain, retention_task.
Reutilizable por el consumer Valkey y el HTTP handler de approve/reject (C13).
"""

from __future__ import annotations

import re
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from app.core.database import engine
from app.modules.audit.models import AuditLog
from app.modules.events.models import Event, EventStatus
from app.modules.rules.service import determine_severity_for_path


_MAX_DIFF_TEXT_BYTES = 1024 * 1024
_DIFF_TRUNCATION_MARKER = "\n... [diff truncated by backend]\n"
_UNIFIED_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$", re.MULTILINE)


def _is_safe_text(value: str) -> bool:
    if "\x00" in value or "\ufffd" in value:
        return False
    return all(
        char in "\t\n\r\f" or not (ord(char) < 32 or 127 <= ord(char) < 160)
        for char in value
    )


def _is_unified_diff(value: str) -> bool:
    lines = value.splitlines()
    if len(lines) < 4 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        return False

    in_hunk = False
    has_change = False
    for line in lines[2:]:
        if _UNIFIED_HUNK.fullmatch(line):
            in_hunk = True
            continue
        if not in_hunk or not line.startswith((" ", "+", "-", "\\ No newline at end of file")):
            return False
        has_change = has_change or line.startswith(("+", "-"))
    return in_hunk and has_change


def _bounded_diff_text(value: Any) -> str | None:
    """Return a UTF-8-safe, bounded textual diff without logging its content."""
    if (
        not isinstance(value, str)
        or not value
        or not _is_safe_text(value)
        or not _is_unified_diff(value)
    ):
        return None

    encoded = value.encode("utf-8")
    if len(encoded) <= _MAX_DIFF_TEXT_BYTES:
        return value

    marker = _DIFF_TRUNCATION_MARKER.encode("utf-8")
    prefix = encoded[: _MAX_DIFF_TEXT_BYTES - len(marker)].decode("utf-8", errors="ignore")
    return prefix + _DIFF_TRUNCATION_MARKER
log = structlog.get_logger()

TERMINAL_STATUSES: frozenset[EventStatus] = frozenset(
    {
        EventStatus.approved,
        EventStatus.rejected,
        EventStatus.auto_restored,
        EventStatus.quarantined,
        EventStatus.alert_only,
        EventStatus.superseded,
    }
)

# RN-72: solo pending tiene out-edges; todos los demás son terminales.
VALID_TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.pending: {EventStatus.approved, EventStatus.rejected, EventStatus.superseded},
    EventStatus.approved: set(),
    EventStatus.rejected: set(),
    EventStatus.auto_restored: set(),
    EventStatus.quarantined: set(),
    EventStatus.alert_only: set(),
    EventStatus.superseded: set(),
}

_MAX_CHAIN = 10
_RETENTION_DAYS = 30


class InvalidTransitionError(Exception):
    def __init__(self, from_status: EventStatus, to_status: EventStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status} → {to_status}")


def validate_transition(from_status: EventStatus, to_status: EventStatus) -> None:
    """Lanza InvalidTransitionError si la transición no está en VALID_TRANSITIONS."""
    if to_status not in VALID_TRANSITIONS.get(from_status, set()):
        raise InvalidTransitionError(from_status, to_status)


# D35/RN-129 (C40): tabla de derivación del status terminal a partir de lo que
# el agente ya publica. El backend es la única autoridad sobre EventStatus —
# no se acepta un `status` de escritura libre del payload (ver ingest_event).
def derive_event_status(action: str | None, action_failed: bool) -> EventStatus:
    """
    Deriva el EventStatus de un evento entrante desde `action` + `action_failed`.

    - auto_restore sin fallo → auto_restored
    - quarantine sin fallo → quarantined
    - alert_only → alert_only (siempre; no ejecuta acción física, nada que fallar)
    - manual_review → pending
    - auto_restore/quarantine con fallo → pending (el archivo sigue adulterado,
      el incidente vuelve a la cola del operador con approve/reject disponibles)
    - action ausente o desconocida → pending (tolerancia hacia adelante, D33)
    """
    if action == "alert_only":
        return EventStatus.alert_only
    if action == "auto_restore":
        return EventStatus.pending if action_failed else EventStatus.auto_restored
    if action == "quarantine":
        return EventStatus.pending if action_failed else EventStatus.quarantined
    return EventStatus.pending


def get_pending_event_for_path(session: Session, path: str) -> Event | None:
    """Retorna el evento pending más reciente para un path, o None."""
    return session.exec(
        select(Event)
        .where(Event.path == path, Event.status == EventStatus.pending)
        .order_by(Event.created_at.desc())
    ).first()


def mark_superseded(session: Session, event_id: int, version: int) -> bool:
    """
    UPDATE optimista: marca el evento como superseded solo si version coincide y status=pending.
    Retorna True si afectó 1 fila, False si hubo carrera (0 filas).
    """
    stmt = (
        sa_update(Event)
        .where(
            Event.id == event_id,
            Event.version == version,
            Event.status == EventStatus.pending,
        )
        .values(status=EventStatus.superseded, version=version + 1)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    return result.rowcount == 1


def compact_chain(session: Session, path: str) -> None:
    """
    Si hay >_MAX_CHAIN eventos superseded para el path, elimina los más antiguos
    excluyendo los referenciados en audit_log. Se llama en la misma transacción
    que ingest_event (RN-98).
    """
    superseded = session.exec(
        select(Event)
        .where(Event.path == path, Event.status == EventStatus.superseded)
        .order_by(Event.created_at.asc())
    ).all()

    if len(superseded) <= _MAX_CHAIN:
        return

    protected_ids: set[int] = {
        r
        for r in session.exec(
            select(AuditLog.target_id).where(
                AuditLog.target_type == "event",
                AuditLog.target_id.isnot(None),
            )
        ).all()
        if r is not None
    }

    excess = len(superseded) - _MAX_CHAIN
    deleted = 0
    for evt in superseded:
        if deleted >= excess:
            break
        if evt.id not in protected_ids:
            session.delete(evt)
            deleted += 1


def ingest_event(
    event_data: dict[str, Any],
    received_at: datetime,
    detected_at: datetime,
) -> Event | None:
    """
    Ingesta un evento válido:
    1. Busca pending para el mismo path.
    2. Si existe → mark_superseded (optimistic); si carrera → retorna None.
    3. Crea el nuevo evento con parent_event_id si hubo superseded.
    4. Llama compact_chain en la misma transacción.
    """
    path = event_data.get("path", "")
    # D35/RN-129 (C40): el status NO se lee del payload — el backend es la
    # única autoridad sobre EventStatus. Se deriva de action/action_failed,
    # que son un vocabulario cerrado producido por el motor de reglas del
    # agente; aceptar un `status` de escritura libre permitiría a un agente
    # comprometido inyectar eventos ya `approved`/`rejected`.
    action = event_data.get("action")
    action_failed = bool(event_data.get("action_failed", False))
    status = derive_event_status(action, action_failed)
    # D36/RN-130 (C41): causa del fallo, puramente explicativa — no influye en
    # la derivación de status ni en la supersesión. Sin validación contra
    # enum (tolerancia hacia adelante, D-8 del design): un valor desconocido
    # se persiste tal cual, truncado a la longitud de la columna; ausente ->
    # None. En la ruta de éxito el agente no escribe la clave.
    action_error = event_data.get("action_error")
    if isinstance(action_error, str):
        action_error = action_error[:64]
    else:
        action_error = None
    hash_expected = event_data.get("hash_expected")
    if isinstance(hash_expected, str):
        hash_expected = hash_expected[:64]
    else:
        hash_expected = None
    diff_text = _bounded_diff_text(event_data.get("diff_text"))


    with Session(engine) as session:
        pending = get_pending_event_for_path(session, path)
        parent_event_id: int | None = None

        if pending is not None and pending.id is not None:
            validate_transition(pending.status, EventStatus.superseded)
            success = mark_superseded(session, pending.id, pending.version)
            if not success:
                log.warning("service.superseded_race", path=path, pending_id=pending.id)
                # FIX-03 (D25, RN-121): re-consultar si el pending fue aprobado/rechazado
                # concurrentemente (en ese caso no hay pending activo → insertar independiente)
                still_pending = get_pending_event_for_path(session, path)
                if still_pending is not None:
                    # Todavía hay un pending activo → skip legítimo
                    log.warning("service.superseded_race.still_pending", path=path)
                    return None
                # No hay pending → continuar inserción como evento independiente
                log.info("service.superseded_race.insert_independent", path=path)
                # parent_event_id ya es None; el flujo continúa normalmente
            else:
                parent_event_id = pending.id

        # D35/RN-129 (C40): terminales de origen agente se persisten con
        # resolved_at = received_at y resolved_by = NULL — identifica una
        # resolución automática sin operador humano. pending (incluido el
        # pending por acción fallida) queda abierto: ambos campos en None.
        is_terminal = status in (
            EventStatus.auto_restored,
            EventStatus.quarantined,
            EventStatus.alert_only,
        )

        event = Event(
            event_id=event_data.get("event_id", ""),
            agent_id=event_data.get("agent_id", ""),
            path=path,
            hash_expected=hash_expected,
            diff_text=diff_text,
            hash_detected=event_data.get("hash_detected") or "",
            status=status,
            # D34/RN-128 (C38): severidad persistida, calculada con la misma
            # lógica que el pipeline de alertas (D-C15-01).
            severity=determine_severity_for_path(path, session),
            action_failed=action_failed,
            action_error=action_error,
            parent_event_id=parent_event_id,
            process_pid=event_data.get("process_pid"),
            process_uid=event_data.get("process_uid"),
            process_exe=event_data.get("process_exe"),
            detected_at=detected_at,
            received_at=received_at,
            resolved_at=received_at if is_terminal else None,
            resolved_by=None,
            # D33/RN-127 (C39): .get() tolerante — un agente viejo sin estas keys
            # ingiere igual, con defaults false/None.
            is_symlink=event_data.get("is_symlink", False),
            symlink_target=event_data.get("symlink_target"),
        )
        session.add(event)
        session.flush()

        if parent_event_id is not None:
            compact_chain(session, path)

        session.commit()
        session.refresh(event)
        return event


async def retention_task() -> None:
    """
    Tarea asyncio periódica: elimina eventos terminales con más de 30 días
    que no están referenciados en audit_log (RN-98).
    """
    while True:
        await asyncio.sleep(3600)
        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        with Session(engine) as session:
            protected_ids: set[int] = {
                r
                for r in session.exec(
                    select(AuditLog.target_id).where(
                        AuditLog.target_type == "event",
                        AuditLog.target_id.isnot(None),
                    )
                ).all()
                if r is not None
            }

            q = select(Event).where(
                Event.status.in_(list(TERMINAL_STATUSES)),
                Event.created_at < cutoff,
            )
            if protected_ids:
                q = q.where(Event.id.notin_(protected_ids))

            to_delete = session.exec(q).all()
            for evt in to_delete:
                session.delete(evt)
            if to_delete:
                session.commit()
                log.info("service.retention_run", deleted=len(to_delete))
