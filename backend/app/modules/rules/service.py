"""
Lógica de negocio del dominio de reglas (Change 12).

Expone: validate_pattern, increment_ruleset_version, publish_rule_sync,
write_audit, create_rule, update_rule, delete_rule, list_rules, get_rule.

Orden de operaciones por escritura (D-F):
  1. Validar input  → ValueError si inválido (mapeado a 422 en router)
  2. Persist Rule   → session.add / session.delete + flush
  3. increment_ruleset_version → new_version
  4. write_audit   → inserta AuditLog
  5. session.commit() — Rule + RulesetVersion + AuditLog atómicos
  6. publish_rule_sync + PublishedCommand inserts — post-commit (D-F trade-off)
"""

from __future__ import annotations

import fnmatch
import json
import re
from datetime import datetime
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlmodel import Session, select

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
    Lee la fila única de RulesetVersion (crea con version=0 si no existe),
    incrementa version, actualiza updated_at, hace flush y retorna el nuevo valor.
    Upsert de fila única — safe en single-instance (RN-75, D-C).
    """
    rv = session.exec(select(RulesetVersion)).first()
    if rv is None:
        rv = RulesetVersion(version=0)
        session.add(rv)
        session.flush()
    rv.version += 1
    rv.updated_at = datetime.utcnow()
    session.add(rv)
    session.flush()
    return rv.version


# ── Fan-out al stream de comandos ─────────────────────────────────────────────


def publish_rule_sync(session: Session, valkey_client: Any, new_version: int) -> int:
    """
    Itera todos los Agent con shared_secret_hex no nulo, construye un payload
    rule_sync por agente, firma con su secret, serializa y publica en STREAM_COMMANDS.
    Inserta un PublishedCommand por mensaje publicado (D9, D10, RN-79).
    Retorna el número de agentes a los que se publicó.
    """
    agents = session.exec(
        select(Agent).where(Agent.shared_secret_hex.isnot(None))
    ).all()

    if not agents:
        log.info("service.rules.publish_rule_sync.no_agents", version=new_version)
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
        valkey_client.xadd(STREAM_COMMANDS, {"data": data})

        cmd = PublishedCommand(
            command_type="rule_sync",
            target_agent_id=agent.agent_id,
            ruleset_version=new_version,
        )
        session.add(cmd)
        count += 1

    session.commit()
    log.info("service.rules.publish_rule_sync.done", version=new_version, agents=count)
    return count


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
    Valida, persiste Rule, incrementa RulesetVersion, escribe AuditLog,
    commit, y luego hace fan-out rule_sync (D-F).
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
    write_audit(session, user_id, "rule_created", rule.id)
    session.commit()
    session.refresh(rule)

    publish_rule_sync(session, valkey_client, new_version)
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
    audit (rule_updated), commit, publish.
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
    rule.updated_at = datetime.utcnow()
    session.add(rule)
    session.flush()

    new_version = increment_ruleset_version(session)
    write_audit(session, user_id, "rule_updated", rule.id)
    session.commit()
    session.refresh(rule)

    publish_rule_sync(session, valkey_client, new_version)
    return rule


def delete_rule(
    session: Session,
    valkey_client: Any,
    user_id: int,
    rule_id: int,
) -> None:
    """
    404 si no existe. Elimina, incrementa, audit (rule_deleted), commit, publish.
    """
    rule = session.exec(select(Rule).where(Rule.id == rule_id)).first()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    captured_id = rule.id
    session.delete(rule)
    session.flush()

    new_version = increment_ruleset_version(session)
    write_audit(session, user_id, "rule_deleted", captured_id)
    session.commit()

    publish_rule_sync(session, valkey_client, new_version)


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
