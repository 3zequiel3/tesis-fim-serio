"""
Lógica de negocio del dominio de eventos (Change 11).

Expone: validate_transition, ingest_event, compact_chain, retention_task.
Reutilizable por el consumer Valkey y el HTTP handler de approve/reject (C13).
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Sequence

import structlog
import sqlalchemy as sa
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from app.core.config import settings
from app.core.database import engine
from app.modules.audit.models import AuditLog
from app.modules.events.models import Event, EventStatus, QuarantineState, RejectedEventAudit
from app.modules.rules.models import PublishedCommand, Rule, RuleSeverity
from app.modules.rules.service import determine_severity_for_path, severity_from_rules

log = structlog.get_logger()

_MAX_DIFF_TEXT_BYTES = 1024 * 1024
_DIFF_TRUNCATION_MARKER = "\n... [diff truncated by backend]\n"
_UNIFIED_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$", re.MULTILINE)

# US-09: hex dump parcial acotado (modo binario del DiffViewer). El agente ya
# limita cada lado a _HEX_DUMP_BYTES=256 bytes (agent/detector.py); a 3 chars
# por byte más el offset por fila, 4096 deja margen holgado sin abrir la
# puerta a un payload arbitrariamente grande de un agente comprometido.
_MAX_HEX_DUMP_CHARS = 4096
_HEX_DUMP_LINE = re.compile(r"^[0-9a-f]{8}  [0-9a-f]{2}(?: [0-9a-f]{2}){0,15}$")


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


def _bounded_hex_dump(value: Any) -> str | None:
    """Return a validated, bounded partial hex dump or None (US-09).

    Same defensive posture as _bounded_diff_text: a malformed, oversized, or
    wrong-typed value (from an untrusted or older agent) is dropped rather
    than persisted or guessed at — never truncated/repaired, just rejected.
    """
    if not isinstance(value, str) or not value:
        return None
    if len(value) > _MAX_HEX_DUMP_CHARS:
        return None
    if not all(_HEX_DUMP_LINE.fullmatch(line) for line in value.split("\n")):
        return None
    return value

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


def quarantine_state_expr() -> sa.ColumnElement:
    """SQL expression for `quarantine_state`, correlated to `events` (D82/RN-176).

    Derived on every read, no column and no write path: the same expression
    feeds the response field and the `GET /events` filter, so `total` and the
    pagination reflect the filter (filtering in Python after the LIMIT would
    return short pages and false totals).

    - base "in quarantine": `status = quarantined`, or `status = rejected` with
      an `acked` `quarantine_file` (D30/RN-124: `ack_status` is the source of
      truth for the physical outcome of a rejection);
    - no base -> `none`;
    - base + `acked` `release_quarantine` with `mode = discard` -> `discarded`;
    - base + `acked` `release_quarantine` with a restore mode -> `released`;
    - otherwise `quarantined`.

    The mode is read from the signed payload (text column holding JSON) with the
    dialect-neutral `JSON` type (Postgres renders `CAST(... AS JSON) ->> 'mode'`;
    SQLite-backed tests still compile `GET /events`). The cast sits inside a CASE on `command_type` so it is only evaluated for
    `release_quarantine` rows (CASE guarantees evaluation order, a WHERE
    conjunction does not); every other row type may carry an empty payload.
    `release_quarantine` is created by Change 65; this only reads it.
    """
    pc = PublishedCommand
    base_qf_acked = (
        sa.select(pc.id)
        .where(
            pc.event_id == Event.id,
            pc.command_type == "quarantine_file",
            pc.ack_status == "acked",
        )
        .exists()
    )
    release_mode = sa.case(
        (pc.command_type == "release_quarantine", sa.cast(pc.payload, sa.JSON)["mode"].as_string()),
        else_=sa.null(),
    )

    def _released(modes: list[str]) -> sa.ColumnElement:
        return (
            sa.select(pc.id)
            .where(
                pc.event_id == Event.id,
                pc.command_type == "release_quarantine",
                pc.ack_status == "acked",
                release_mode.in_(modes),
            )
            .exists()
        )

    in_quarantine = sa.or_(
        Event.status == EventStatus.quarantined,
        sa.and_(Event.status == EventStatus.rejected, base_qf_acked),
    )
    return sa.case(
        (sa.not_(in_quarantine), QuarantineState.none.value),
        (_released(["discard"]), QuarantineState.discarded.value),
        (_released(["restore_original", "restore_baseline"]), QuarantineState.released.value),
        else_=QuarantineState.quarantined.value,
    )


def get_quarantine_states(session: Session, event_ids: list[int]) -> dict[int, QuarantineState]:
    """`quarantine_state` for a set of events, with the same expression as the filter."""
    if not event_ids:
        return {}
    rows = session.exec(
        sa.select(Event.id, quarantine_state_expr()).where(Event.id.in_(event_ids))  # type: ignore[union-attr]
    ).all()
    return {row[0]: QuarantineState(row[1]) for row in rows}


class InvalidTransitionError(Exception):
    def __init__(self, from_status: EventStatus, to_status: EventStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status} → {to_status}")


class IngestDisposition(str, Enum):
    """Resultado materializado de un intento transaccional de ingesta."""

    persisted = "persisted"
    duplicate = "duplicate"
    supersede_race = "supersede_race"
    rate_limited = "rate_limited"
    # Batch path only: the candidate hit `InvalidTransitionError` before writing anything.
    invalid_transition = "invalid_transition"


@dataclass(frozen=True)
class IngestOutcome:
    disposition: IngestDisposition
    event: Event | None = None
    # Change `ingest-batched-persistence` (task 1.4): wall time of the
    # `session.commit()` of the per-event path, in milliseconds. `None` where there was
    # no commit of its own. It is measured with two `perf_counter` reads (negligible),
    # never logged from the executor thread: the consumer emits it under
    # `fim_profile_ingest`.
    commit_ms: float | None = None


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


# US-08 criterio 2: "tipo de acción" siempre visible en el detalle. `action`
# (RuleAction) no sobrevive al ingest más allá de derivar EventStatus (ver
# derive_event_status arriba) — no hay columna nueva ni migración. RN-72 dice
# que `pending` es el único estado con out-edges (VALID_TRANSITIONS), así que
# approved/rejected/superseded solo pueden haberse originado en un ingest con
# action=manual_review; auto_restored/quarantined/alert_only son terminales
# sin out-edges y mapean 1:1 a la acción que los produjo.
def derive_action_type(event_status: EventStatus) -> str:
    """Deriva el tipo de acción a mostrar en el detalle desde el status."""
    if event_status == EventStatus.auto_restored:
        return "auto_restore"
    if event_status == EventStatus.quarantined:
        return "quarantine"
    if event_status == EventStatus.alert_only:
        return "alert_only"
    return "manual_review"


# US-10: la cadena se indexa por path (RN-21/RN-23). Un evento sin path
# (D51/RN-145, ej. detection_gap) no participa del mecanismo — su "cadena" es
# únicamente él mismo, nunca se agrupa con otros eventos sin ruta (un filtro
# `Event.path == None` traducido a `IS NULL` agruparía a todos los pathless
# entre sí, que es exactamente lo que D51/RN-145 dice que no debe pasar).
def get_event_chain(session: Session, event: Event) -> list[Event]:
    """Retorna todos los eventos del mismo path que `event`, orden cronológico ascendente."""
    if event.path is None:
        return [event]
    return list(
        session.exec(
            select(Event)
            .where(Event.path == event.path)
            .order_by(Event.created_at.asc(), Event.id.asc())
        ).all()
    )


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


def compact_chain(session: Session, path: str) -> list[int]:
    """
    Si hay >_MAX_CHAIN eventos superseded para el path, elimina los más antiguos
    excluyendo los referenciados en audit_log. Se llama en la misma transacción
    que ingest_event (RN-98). Devuelve los `id` de las filas eliminadas (el lote de
    `ingest-batched-persistence` los usa para no notificar eventos ya compactados).
    """
    superseded = session.exec(
        select(Event)
        .where(Event.path == path, Event.status == EventStatus.superseded)
        .order_by(Event.created_at.asc())
    ).all()

    if len(superseded) <= _MAX_CHAIN:
        return []

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
    deleted_ids: list[int] = []
    for evt in superseded:
        if len(deleted_ids) >= excess:
            break
        if evt.id not in protected_ids:
            session.delete(evt)
            deleted_ids.append(evt.id)
    return deleted_ids


@dataclass
class _IngestBatchContext:
    """
    State shared by the candidates of one ingest transaction (change
    `ingest-batched-persistence`, D-3). `preloaded=False` is the one-event context of
    the per-event path: every lookup goes to the database as before this change.
    `preloaded=True` is the batch: dedup ids, the latest `pending` per path and the
    ruleset were read once, and are kept in step in memory after each insertion.
    """

    preloaded: bool = False
    known_event_ids: set[str] = field(default_factory=set)
    # path -> latest `pending` event (None: no pending). Detached objects: only id/version/status are read.
    pending_by_path: dict[str, Event | None] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    # `Event.id` of the rows deleted by `compact_chain` during the batch.
    removed_event_ids: set[int] = field(default_factory=set)
    # Rate-limit tokens consumed per agent (refunded if the transaction rolls back).
    tokens_by_agent: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestBatchItem:
    """One validated candidate of a batch, in stream order."""

    event_data: dict[str, Any]
    received_at: datetime
    detected_at: datetime
    agent_id: str


@dataclass
class IngestBatchResult:
    outcomes: list[IngestOutcome]  # one per item, same order
    removed_event_ids: set[int]
    candidate_ms: list[float]  # time of each candidate inside the transaction
    ingest_db_ms: float  # the whole transaction without the COMMIT
    commit_ms: float


def _ingest_into_session(
    session: Session,
    ctx: _IngestBatchContext,
    event_data: dict[str, Any],
    received_at: datetime,
    detected_at: datetime,
    accept_new: Callable[[], bool] | None,
) -> IngestOutcome:
    """
    Ingest core shared by the per-event path and the batch (D-3): everything that
    used to run inside the `with Session` of `_ingest_event_outcome` except opening
    the session and the `COMMIT`.
    1. Busca pending para el mismo path.
    2. Si existe -> mark_superseded (optimistic); si carrera -> supersede_race.
    3. Crea el nuevo evento con parent_event_id si hubo superseded (flush, sin commit).
    4. Llama compact_chain en la misma transaccion.
    """
    # D51/RN-145: sin default. El "" que había acá era la clave con la que
    # get_pending_event_for_path buscaba el pending anterior para supersedirlo
    # — con ella, TODOS los eventos sin ruta (p. ej. detection_gap) se
    # supersederían entre sí bajo la misma clave, y cada brecha nueva
    # borraría la anterior de la vista del operador. El nulo debe llegar
    # nulo hasta la columna.
    path = event_data.get("path")
    # D51/RN-145: vocabulario que el agente ya emite, persistido sin
    # validación contra enum (mismo criterio de tolerancia hacia adelante que
    # action/action_error, D33/D36/RN-130). Ausente (clave faltante, agente
    # anterior a esta change) -> default del modelo, 'file_modified'.
    event_type = event_data.get("event_type", "file_modified")
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
    # D80/RN-174: tolerante hacia adelante, mismo criterio que D72 para
    # queue_pressure_high. isinstance y no bool(): "yes"/0/1 no son booleanos y
    # no deben convertirse en un dato falso. No influye en status ni severidad.
    detected_offline_raw = event_data.get("detected_offline")
    detected_offline: bool | None
    if isinstance(detected_offline_raw, bool):
        detected_offline = detected_offline_raw
    else:
        detected_offline = None
        if detected_offline_raw is not None:
            log.warning(
                "consumer.detected_offline_invalid",
                event_id=event_data.get("event_id"),
                value_type=type(detected_offline_raw).__name__,
            )

    hash_expected = event_data.get("hash_expected")
    if isinstance(hash_expected, str):
        hash_expected = hash_expected[:64]
    else:
        hash_expected = None
    diff_text = _bounded_diff_text(event_data.get("diff_text"))
    # US-09: is_binary tolerante hacia adelante (mismo criterio que
    # is_symlink/action_failed) — ausente en un agente anterior a esta
    # change -> False. hex_dump_before/hex_dump_after pasan por la misma
    # validación defensiva bounded que diff_text.
    is_binary = bool(event_data.get("is_binary", False))
    hex_dump_before = _bounded_hex_dump(event_data.get("hex_dump_before"))
    hex_dump_after = _bounded_hex_dump(event_data.get("hex_dump_after"))

    if ctx.preloaded:
        # Batch: dedup against the block-loaded ids (database + earlier in the batch).
        if event_data.get("event_id", "") in ctx.known_event_ids:
            return IngestOutcome(IngestDisposition.duplicate)
    else:
        duplicate = session.exec(
            select(Event).where(Event.event_id == event_data.get("event_id", ""))
        ).first()
        if duplicate is not None:
            session.expunge(duplicate)
            return IngestOutcome(IngestDisposition.duplicate, duplicate)

    # Reservar capacidad solo después de deduplicar en la transacción.
    if accept_new is not None and not accept_new():
        return IngestOutcome(IngestDisposition.rate_limited)

    # D51/RN-145 (D-6 del design): un evento sin ruta no participa de la
    # supersesión por path — get_pending_event_for_path NUNCA se invoca
    # con path=None, mantiene su firma `path: str`.
    if path is None:
        pending = None
    elif ctx.preloaded:
        pending = ctx.pending_by_path.get(path)
    else:
        pending = get_pending_event_for_path(session, path)
    parent_event_id: int | None = None

    if pending is not None and pending.id is not None:
        try:
            validate_transition(pending.status, EventStatus.superseded)
        except InvalidTransitionError:
            if not ctx.preloaded:
                raise  # per-event path: `_handle_message` handles the propagation
            return IngestOutcome(IngestDisposition.invalid_transition)
        success = mark_superseded(session, pending.id, pending.version)
        if not success:
            log.warning("service.superseded_race", path=path, pending_id=pending.id)
            # FIX-03 (D25, RN-121): re-consultar si el pending fue aprobado/rechazado
            # concurrentemente (en ese caso no hay pending activo → insertar independiente)
            still_pending = get_pending_event_for_path(session, path)
            if still_pending is not None:
                # Todavía hay un pending activo → skip legítimo
                log.warning("service.superseded_race.still_pending", path=path)
                if ctx.preloaded:
                    session.expunge(still_pending)
                    ctx.pending_by_path[path] = still_pending
                return IngestOutcome(IngestDisposition.supersede_race)
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

    # D51/RN-145 (D-7 del design): un evento sin ruta recibe severidad
    # `high` fija, SIN consultar el ruleset — determine_severity_for_path
    # no matchea ninguna regla sin path y caería en `low` (D-C15-01), que
    # es lo contrario de lo que significa una pérdida de cobertura. La
    # excepción se dispara por AUSENCIA DE RUTA, no por
    # event_type == "detection_gap": un tipo de evento futuro sin ruta
    # hereda el tratamiento correcto sin tocar este código. `high` y no
    # `critical`: una brecha de detección es una pérdida de garantía, no
    # una violación de integridad confirmada (D34/RN-128 sigue siendo la
    # única autoridad — el valor que el agente proponga se ignora igual).
    severity = (
        RuleSeverity.high
        if path is None
        else (
            severity_from_rules(path, ctx.rules)
            if ctx.preloaded
            else determine_severity_for_path(path, session)
        )
    )

    event = Event(
        event_id=event_data.get("event_id", ""),
        agent_id=event_data.get("agent_id", ""),
        event_type=event_type,
        path=path,
        hash_detected=event_data.get("hash_detected") or "",
        hash_expected=hash_expected,
        diff_text=diff_text,
        is_binary=is_binary,
        hex_dump_before=hex_dump_before,
        hex_dump_after=hex_dump_after,
        status=status,
        severity=severity,
        action_failed=action_failed,
        action_error=action_error,
        detected_offline=detected_offline,
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

    # D51/RN-145 (D-6 del design): la condición `parent_event_id is not
    # None` ya implica `path is not None` por construcción — sólo hay
    # parent_event_id cuando hubo supersesión, y un evento sin ruta nunca
    # supersede (ver la guarda de arriba). Se declara la guarda explícita
    # igual, para que un refactor futuro no la pierda: un compact_chain
    # sobre ruta nula borraría eventos de brecha de detección al llegar
    # al umbral de 10.
    if parent_event_id is not None and path is not None:
        ctx.removed_event_ids.update(compact_chain(session, path))

    # Separar la fila ya materializada antes del commit evita que el
    # despacho dispare un SELECT por expiración del objeto.
    session.expunge(event)
    if ctx.preloaded:
        # Keep the in-memory view of the batch in step with what was just written: the
        # next candidate of the same path supersedes THIS event if it stayed pending, and
        # a terminal event leaves no pending behind (a terminal is never pending).
        ctx.known_event_ids.add(event.event_id)
        if path is not None:
            ctx.pending_by_path[path] = event if event.status == EventStatus.pending else None
    return IngestOutcome(IngestDisposition.persisted, event)


def _ingest_event_outcome(
    event_data: dict[str, Any],
    received_at: datetime,
    detected_at: datetime,
    *,
    accept_new: Callable[[], bool] | None = None,
) -> IngestOutcome:
    """
    Per-event ingest (own `Session`, own transaction, own `COMMIT`): the path used
    outside a batch and the replay of a batch that hit a deterministic error.
    Signature and behavior are unchanged; the work lives in `_ingest_into_session`.
    """
    with Session(engine) as session:
        outcome = _ingest_into_session(
            session, _IngestBatchContext(), event_data, received_at, detected_at, accept_new
        )
        if outcome.disposition != IngestDisposition.persisted:
            return outcome
        t_commit = time.perf_counter()
        session.commit()
        commit_ms = (time.perf_counter() - t_commit) * 1000
        return IngestOutcome(IngestDisposition.persisted, outcome.event, commit_ms)


def _ingest_batch(
    items: Sequence[IngestBatchItem],
    accept_new_for: Callable[[str], Callable[[], bool]],
    refund: Callable[[str, int], None] | None = None,
) -> IngestBatchResult:
    """
    Persist the validated candidates of a consumer batch in ONE transaction (change
    `ingest-batched-persistence`, amplification of 2026-10-03 of D87/RN-181), in
    stream order, with one `COMMIT`. One call, one thread of the ingest executor
    (D75/RN-169): no concurrency between candidates.

    Reads once: the ids already in the database (block dedup), the latest `pending`
    per path and the ruleset. The per-candidate semantics (dedup, rate limit,
    `superseded` chain, optimistic UPDATE and race re-query D25/RN-121, compaction
    RN-98) are those of `_ingest_into_session`. `accept_new_for(agent_id)` returns
    the rate-limit check of that agent; `refund(agent_id, n)` gives the consumed
    tokens back if the transaction rolls back (D-6). On any exception the
    transaction is rolled back, the tokens are refunded and the error propagates.
    """
    ctx = _IngestBatchContext(preloaded=True)
    outcomes: list[IngestOutcome] = []
    candidate_ms: list[float] = []
    with Session(engine) as session:
        try:
            t_start = time.perf_counter()
            event_ids = [i.event_data.get("event_id", "") for i in items]
            if event_ids:
                ctx.known_event_ids.update(
                    session.exec(select(Event.event_id).where(Event.event_id.in_(event_ids))).all()  # type: ignore[union-attr]
                )
            paths = sorted({p for i in items if (p := i.event_data.get("path")) is not None})
            for path in paths:
                ctx.pending_by_path[path] = None
            if paths:
                # Newest first: the first row per path is the latest pending. Portable to the
                # SQLite of the tests (no DISTINCT ON).
                for pending in session.exec(
                    select(Event)
                    .where(Event.path.in_(paths), Event.status == EventStatus.pending)  # type: ignore[union-attr]
                    .order_by(Event.created_at.desc(), Event.id.desc())
                ).all():
                    if ctx.pending_by_path[pending.path] is None:
                        ctx.pending_by_path[pending.path] = pending
                    # Detached, so later queries of the batch return fresh instances.
                    session.expunge(pending)
            ctx.rules = list(session.exec(select(Rule)).all())
            for rule in ctx.rules:
                session.expunge(rule)

            for item in items:
                t_item = time.perf_counter()
                check = accept_new_for(item.agent_id)

                def counted(check=check, agent_id=item.agent_id) -> bool:
                    allowed = check()
                    if allowed:
                        ctx.tokens_by_agent[agent_id] = ctx.tokens_by_agent.get(agent_id, 0) + 1
                    return allowed

                outcome = _ingest_into_session(
                    session, ctx, item.event_data, item.received_at, item.detected_at, counted
                )
                outcomes.append(outcome)
                candidate_ms.append((time.perf_counter() - t_item) * 1000)
            ingest_db_ms = (time.perf_counter() - t_start) * 1000
            t_commit = time.perf_counter()
            session.commit()
            commit_ms = (time.perf_counter() - t_commit) * 1000
        except Exception:
            # Any failure, not only SQLAlchemyError (e.g. a TypeError on an unexpected payload
            # shape): the transaction never committed, so roll back and give the tokens back.
            session.rollback()
            if refund is not None:
                for agent_id, tokens in ctx.tokens_by_agent.items():
                    refund(agent_id, tokens)
            raise
    return IngestBatchResult(outcomes, set(ctx.removed_event_ids), candidate_ms, ingest_db_ms, commit_ms)


def ingest_event(
    event_data: dict[str, Any],
    received_at: datetime,
    detected_at: datetime,
) -> Event | None:
    """API de dominio compatible; el consumer usa el resultado tipado interno."""
    return _ingest_event_outcome(event_data, received_at, detected_at).event


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


def purge_rejected_events_audit(
    session_factory: Callable[[], Session],
    now: datetime,
    days: int,
    batch_size: int = 1000,
) -> int:
    """
    Elimina en lotes las filas de rejected_events_audit con received_at
    anterior a `now - days` (D65/RN-159). `rejected_events_audit` guarda
    payloads rechazados truncados (D4) y crece sin límite sin esta retención.

    Cada lote corre en su propia sesión/transacción (session_factory() se
    invoca una vez por lote) y borra a lo sumo batch_size filas por
    `id IN (SELECT id … WHERE received_at < cutoff ORDER BY id LIMIT batch)`,
    para no bloquear la tabla con una transacción larga mientras el consumer
    sigue insertando rechazos. Repite hasta que un lote borre menos de
    batch_size filas. Portable a SQLite (tests en memoria) y Postgres.

    NUNCA referencia AuditLog/audit_log — esa tabla tiene retención ilimitada
    y este change no la toca (W18/RN-94, ratificada).

    Retorna el total de filas eliminadas en la corrida.
    """
    cutoff = now - timedelta(days=days)
    total_deleted = 0

    while True:
        with session_factory() as session:
            batch_ids = (
                select(RejectedEventAudit.id)
                .where(RejectedEventAudit.received_at < cutoff)
                .order_by(RejectedEventAudit.id.asc())
                .limit(batch_size)
            )
            stmt = sa_delete(RejectedEventAudit).where(RejectedEventAudit.id.in_(batch_ids))
            result = session.execute(stmt)
            session.commit()
            deleted = result.rowcount or 0
            total_deleted += deleted

        if deleted < batch_size:
            break

    return total_deleted


async def rejected_events_retention_task() -> None:
    """
    Tarea asyncio periódica (D65/RN-159, una vez por hora, igual cadencia que
    RN-98): elimina en lotes las filas de rejected_events_audit más antiguas
    que settings.rejected_events_retention_days.

    Separada de retention_task() para aislar fallos (design.md Decisión 5):
    un error transitorio de DB se registra y NO termina la tarea, que
    reintenta en la siguiente iteración. NUNCA purga audit_log (W18/RN-94).
    """
    while True:
        await asyncio.sleep(3600)
        try:
            deleted = purge_rejected_events_audit(
                lambda: Session(engine),
                datetime.now(timezone.utc),
                settings.rejected_events_retention_days,
            )
        except Exception:
            log.error("service.rejected_retention_error", exc_info=True)
            continue

        if deleted > 0:
            log.info("service.rejected_retention_run", deleted=deleted)
