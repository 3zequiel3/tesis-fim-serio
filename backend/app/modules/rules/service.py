"""
Lógica de negocio del dominio de reglas (Change 12).

Expone: validate_pattern, increment_ruleset_version, enqueue_rule_sync,
publish_pending_commands, publish_rule_sync, write_audit, create_rule,
update_rule, delete_rule, list_rules, get_rule.

Orden de operaciones por escritura (D-F, revisado por H6 — outbox):
  1. Validar input  → ValueError si inválido (mapeado a 422 en router)
  2. Persist Rule   → session.add / session.delete + flush
  3. increment_ruleset_version → new_version (atómico, M6)
  4. enqueue_rule_sync → persiste el/los PublishedCommand `pending` (payload
     firmado completo) en la MISMA transacción — outbox (H6, RN-79, RN-123)
  5. write_audit   → inserta AuditLog
  6. session.commit() — Rule + RulesetVersion + PublishedCommand(pending) + AuditLog atómicos
  7. publish_pending_commands — intento inmediato best-effort, post-commit.
     Si Valkey está caído, los comandos quedan `pending`; el background task
     (`publish_pending_commands` corrido periódicamente, ver main.py lifespan)
     reintenta hasta publicarlos sin intervención manual.
"""

from __future__ import annotations

import fnmatch
import json
import re
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import update as sa_update
from sqlmodel import Session, select
from valkey.exceptions import ValkeyError

from app.core.streams import SCHEMA_VERSION, STREAM_COMMANDS, sign_payload
from app.modules.agents.models import Agent
from app.modules.audit.models import AuditLog
from app.modules.rules.models import PublishedCommand, Rule, RuleAction, RuleSeverity, RulesetVersion

log = structlog.get_logger()

# RN-09: orden canónico de severidad (critical=0 es el más grave)
SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

VALID_SEVERITIES: frozenset[str] = frozenset(SEVERITY_ORDER)
VALID_ACTIONS: frozenset[str] = frozenset(a.value for a in RuleAction)


# ── Validación ────────────────────────────────────────────────────────────────


def validate_pattern(pattern: str) -> None:
    """
    Valida que pattern sea un glob fnmatch compilable y no vacío (RN-08, RN-58).
    Lanza ValueError si inválido — el router lo mapea a 422.
    """
    if not pattern or not pattern.strip():
        raise ValueError("pattern must not be empty")
    try:
        regex = fnmatch.translate(pattern)
        re.compile(regex)
    except Exception as exc:
        raise ValueError(f"invalid glob pattern: {exc}") from exc


# ── Counter de versión ────────────────────────────────────────────────────────


def increment_ruleset_version(session: Session) -> int:
    """
    Incrementa atómicamente el counter global RulesetVersion (RN-75, D-C, M6)
    mediante una única sentencia `UPDATE ... RETURNING`, evitando el race de
    lee-modifica-escribe (`SELECT` + `version += 1` + `flush`) bajo requests
    concurrentes. Única implementación compartida por `rules/service.py` y
    `actions/service.py` — no debe duplicarse (ver design.md → M6).

    Si la fila única todavía no existe (bootstrap), la crea con version=1.
    """
    stmt = (
        sa_update(RulesetVersion)
        .values(version=RulesetVersion.version + 1, updated_at=datetime.now(timezone.utc))
        .returning(RulesetVersion.version)
    )
    result = session.execute(stmt).first()
    if result is not None:
        return result[0]

    # Bootstrap: la fila única de RulesetVersion no existe todavía.
    rv = RulesetVersion(version=1)
    session.add(rv)
    session.flush()
    return rv.version


# ── Fan-out al stream de comandos ─────────────────────────────────────────────


def enqueue_rule_sync(session: Session, new_version: int) -> int:
    """
    H6 — outbox (paso 1/2): construye el payload rule_sync firmado por cada
    Agent con shared_secret_hex no nulo y lo persiste como PublishedCommand
    `pending`, SIN publicarlo todavía y SIN hacer commit — el caller debe
    incluir este insert en la MISMA transacción que Rule + RulesetVersion
    (RN-79, RN-123). La publicación efectiva la hace `publish_pending_commands`.
    Retorna la cantidad de comandos encolados.
    """
    agents = session.exec(
        select(Agent).where(Agent.shared_secret_hex.isnot(None))
    ).all()

    if not agents:
        log.info("service.rules.enqueue_rule_sync.no_agents", version=new_version)
        return 0

    # Obtener todas las reglas para incluirlas inline (agente las requiere en payload)
    rules = session.exec(select(Rule)).all()
    rules_list = [
        {
            "id": r.id,
            "pattern": r.pattern,
            "severity": r.severity.value,
            "action": r.action.value,
            "negated": r.pattern.startswith("!"),
        }
        for r in rules
    ]

    count = 0
    for agent in agents:
        secret_bytes = bytes.fromhex(agent.shared_secret_hex)  # type: ignore[arg-type]
        payload: dict[str, Any] = {
            "type": "rule_sync",
            "target_agent_id": agent.agent_id,
            "ruleset_version": new_version,
            "schema_version": SCHEMA_VERSION,
            "rules": rules_list,
        }
        payload["signature"] = sign_payload(secret_bytes, payload)
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))

        cmd = PublishedCommand(
            command_type="rule_sync",
            target_agent_id=agent.agent_id,
            ruleset_version=new_version,
            payload=data,
            status="pending",
            published_at=None,
        )
        session.add(cmd)
        count += 1

    log.info("service.rules.enqueue_rule_sync.done", version=new_version, agents=count)
    return count


def publish_pending_commands(session: Session, valkey_client: Any) -> int:
    """
    H6 — outbox (paso 2/2): toma los PublishedCommand `pending`, en orden, y
    los publica al stream `commands` (XADD) usando el payload ya firmado y
    persistido. Marca cada fila `published` al confirmar el XADD, con commit
    por fila para no perder progreso parcial.

    Si Valkey está caído, el primer XADD falla con ValkeyError: se loguea y
    se detiene el barrido (el resto queda `pending`) — no se pierde ningún
    comando ni se duplica la fila. Pensado para correr tanto de forma
    inmediata (best-effort post-commit) como periódica (background task,
    ver main.py lifespan) para reintentar hasta que la publicación tenga éxito.

    Retorna la cantidad de comandos publicados en esta corrida.
    """
    pending = session.exec(
        select(PublishedCommand)
        .where(PublishedCommand.status == "pending")
        .order_by(PublishedCommand.id)
    ).all()

    published = 0
    for cmd in pending:
        try:
            valkey_client.xadd(STREAM_COMMANDS, {"data": cmd.payload})
        except ValkeyError as exc:
            log.warning(
                "service.rules.publish_pending_commands.valkey_unavailable",
                command_id=cmd.id,
                error=str(exc),
            )
            break

        cmd.status = "published"
        cmd.published_at = datetime.now(timezone.utc)
        session.add(cmd)
        session.commit()
        published += 1

    if published:
        log.info("service.rules.publish_pending_commands.done", published=published)
    return published


def publish_rule_sync(session: Session, valkey_client: Any, new_version: int) -> int:
    """
    Wrapper de conveniencia síncrono: enqueue_rule_sync + intento inmediato de
    publish_pending_commands en una sola llamada. Usado por los callers que
    necesitan el comportamiento previo a H6 (encolar y publicar en el mismo
    paso) y por los tests unitarios de esta función. Si Valkey está caído,
    los comandos quedan `pending` en el outbox — no lanza excepción.
    Retorna la cantidad de comandos encolados (no necesariamente publicados
    si Valkey estuvo caído durante el intento).
    """
    enqueued = enqueue_rule_sync(session, new_version)
    if enqueued == 0:
        return 0
    session.commit()
    publish_pending_commands(session, valkey_client)
    return enqueued


# ── Audit log ─────────────────────────────────────────────────────────────────


def write_audit(session: Session, user_id: int, action: str, rule_id: int | None) -> None:
    """Inserta AuditLog con target_type='rule' (RN-94)."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        target_type="rule",
        target_id=rule_id,
    )
    session.add(entry)


# ── CRUD ──────────────────────────────────────────────────────────────────────


def create_rule(
    session: Session,
    valkey_client: Any,
    user_id: int,
    data: dict[str, Any],
) -> Rule:
    """
    Valida, persiste Rule, incrementa RulesetVersion, encola el fan-out
    rule_sync como outbox pendiente (H6), escribe AuditLog, commit — todo en
    una única transacción — y luego intenta publicar de inmediato (best-effort;
    si Valkey está caído, el background task reintenta).
    """
    pattern: str = data.get("pattern", "")
    severity_val: str = data.get("severity", "")
    action_val: str = data.get("action", "")

    validate_pattern(pattern)

    rule = Rule(
        pattern=pattern,
        severity=RuleSeverity(severity_val),
        action=RuleAction(action_val),
    )
    session.add(rule)
    session.flush()

    new_version = increment_ruleset_version(session)
    enqueue_rule_sync(session, new_version)  # H6: outbox pending, misma transacción
    write_audit(session, user_id, "rule_created", rule.id)
    session.commit()
    session.refresh(rule)

    publish_pending_commands(session, valkey_client)
    return rule


def update_rule(
    session: Session,
    valkey_client: Any,
    user_id: int,
    rule_id: int,
    data: dict[str, Any],
) -> Rule:
    """
    404 si no existe. Valida, actualiza campos + updated_at, incrementa,
    encola el outbox rule_sync (H6), audit (rule_updated), commit, publica
    de inmediato (best-effort).
    """
    rule = session.exec(select(Rule).where(Rule.id == rule_id)).first()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    pattern: str = data.get("pattern", rule.pattern)
    severity_val: str = data.get("severity", rule.severity.value)
    action_val: str = data.get("action", rule.action.value)

    validate_pattern(pattern)

    rule.pattern = pattern
    rule.severity = RuleSeverity(severity_val)
    rule.action = RuleAction(action_val)
    rule.updated_at = datetime.now(timezone.utc)
    session.add(rule)
    session.flush()

    new_version = increment_ruleset_version(session)
    enqueue_rule_sync(session, new_version)  # H6: outbox pending, misma transacción
    write_audit(session, user_id, "rule_updated", rule.id)
    session.commit()
    session.refresh(rule)

    publish_pending_commands(session, valkey_client)
    return rule


def delete_rule(
    session: Session,
    valkey_client: Any,
    user_id: int,
    rule_id: int,
) -> None:
    """
    404 si no existe. Elimina, incrementa, encola el outbox rule_sync (H6),
    audit (rule_deleted), commit, publica de inmediato (best-effort).
    """
    rule = session.exec(select(Rule).where(Rule.id == rule_id)).first()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    captured_id = rule.id
    session.delete(rule)
    session.flush()

    new_version = increment_ruleset_version(session)
    enqueue_rule_sync(session, new_version)  # H6: outbox pending, misma transacción
    write_audit(session, user_id, "rule_deleted", captured_id)
    session.commit()

    publish_pending_commands(session, valkey_client)


def list_rules(session: Session) -> list[Rule]:
    """SELECT todas las reglas y ordena en memoria por severity canónico, luego id (RN-09)."""
    rules = session.exec(select(Rule)).all()
    return sorted(
        rules,
        key=lambda r: (SEVERITY_ORDER.get(r.severity.value, 99), r.id or 0),
    )


def get_rule(session: Session, rule_id: int) -> Rule | None:
    """Retorna la regla con el id dado, o None si no existe."""
    return session.exec(select(Rule).where(Rule.id == rule_id)).first()


# ── Background task — outbox poller (H6) ────────────────────────────────────

_OUTBOX_POLL_INTERVAL_SECONDS = 30


async def outbox_publisher_task() -> None:
    """
    H6: tarea asyncio periódica que reintenta publicar los PublishedCommand
    `pending` (outbox de rule_sync) que quedaron sin entregar por una caída
    de Valkey en el intento inmediato de create/update/delete_rule. Corrida
    desde el lifespan de FastAPI (ver main.py), igual que `retention_task`.
    """
    import asyncio

    from app.core.database import engine
    from app.core.valkey import get_valkey_client

    while True:
        await asyncio.sleep(_OUTBOX_POLL_INTERVAL_SECONDS)
        try:
            valkey_client = get_valkey_client()
        except RuntimeError:
            # Valkey todavía no fue inicializado (arranque temprano) — reintentar en el próximo ciclo.
            continue
        with Session(engine) as session:
            publish_pending_commands(session, valkey_client)
