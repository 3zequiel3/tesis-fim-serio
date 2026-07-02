"""
Lógica de negocio para registro, bootstrap y gestión de agentes FIM (Change 06, C14).
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.core.pki import issue_certificate
from app.modules.agents.models import (
    Agent,
    AgentBootstrapRequest,
    AgentBootstrapResponse,
    AgentRegisterRequest,
    AgentResponse,
    AgentStatus,
)

_ph = PasswordHasher()


def register_agent(req: AgentRegisterRequest, session: Session) -> Agent:
    existing = session.get(Agent, req.agent_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"agent '{req.agent_id}' already registered",
        )

    hashed = _ph.hash(req.bootstrap_secret)
    agent = Agent(
        agent_id=req.agent_id,
        status=AgentStatus.offline,
        bootstrap_secret_hash=hashed,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


def bootstrap_agent(
    req: AgentBootstrapRequest,
    session: Session,
    ca_cert_path: str,
    ca_key_path: str,
) -> AgentBootstrapResponse:
    agent = session.get(Agent, req.agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    if not agent.bootstrap_secret_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    try:
        _ph.verify(agent.bootstrap_secret_hash, req.bootstrap_secret)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    _validate_csr(req.csr_pem, req.agent_id)

    cert_pem = issue_certificate(req.csr_pem, ca_cert_path, ca_key_path)
    ca_cert_pem = Path(ca_cert_path).read_text()

    shared_secret = secrets.token_bytes(32)
    master_secret = secrets.token_bytes(32)

    agent.shared_secret_hex = shared_secret.hex()
    agent.bootstrap_secret_hash = None
    session.add(agent)
    session.commit()

    return AgentBootstrapResponse(
        cert_pem=cert_pem,
        ca_cert_pem=ca_cert_pem,
        shared_secret_hex=shared_secret.hex(),
        master_secret_hex=master_secret.hex(),
    )


class PendingEventsExist(Exception):
    """Hay eventos pending del agente — requiere force=True para rescan."""

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(f"pending_events_exist: {count}")


# ── Gestión de agentes (C14) ──────────────────────────────────────────────────


def _agent_to_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        agent_id=agent.agent_id,
        status=agent.status,
        last_heartbeat=agent.last_heartbeat,
        queue_pressure=agent.queue_pressure,
        ruleset_version_applied=agent.ruleset_version_applied,
        watch_paths=agent.watch_paths or [],
    )


def list_agents(db: Session) -> list[AgentResponse]:
    """Retorna todos los agentes registrados con su estado operacional."""
    agents = db.exec(select(Agent)).all()
    return [_agent_to_response(a) for a in agents]


def get_agent(db: Session, agent_id: str) -> AgentResponse:
    """Retorna el detalle del agente o raise 404."""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return _agent_to_response(agent)


def update_agent_config(
    db: Session,
    valkey_client: Any,
    agent_id: str,
    watch_paths: list[str],
    user_id: int,
) -> AgentResponse:
    """
    Actualiza watch_paths del agente (replace-all), incrementa ruleset_version,
    publica update_config HMAC-signed y registra en audit_log.

    D-C14-02: semántica replace-all — el array anterior es completamente sobreescrito.
    D-C14-05: el ruleset_version se incrementa aquí antes de publicar.
    """
    from app.modules.agents.streams import publish_update_config
    from app.modules.audit.models import AuditLog
    from app.modules.rules.service import increment_ruleset_version

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    # Persistir watch_paths
    agent.watch_paths = watch_paths
    db.add(agent)
    db.flush()

    # Incrementar ruleset_version (mismo counter que C12/C13)
    new_version = increment_ruleset_version(db)

    # D5/RN-106 (C36): ruleset_version_applied NO avanza acá — solo avanza
    # cuando el consumer de command_ack confirma la ejecución del comando
    # update_config (agents/command_ack_consumer.py). Antes de C36 este
    # método lo avanzaba al publicar, violando la semántica normativa.

    # Registrar audit_log — M5: JSON válido vía json.dumps (antes: f-string
    # sobre str(list), que produce comillas simples inválidas en JSON y se
    # rompe si un path contiene comillas dobles o barras invertidas).
    audit = AuditLog(
        user_id=user_id,
        action="agent_config",
        target_type="agent",
        detail=json.dumps({"agent_id": agent_id, "watch_paths": watch_paths}),
    )
    db.add(audit)
    db.commit()
    db.refresh(agent)

    # Publicar update_config post-commit (mismo patrón D-F que rules.py)
    publish_update_config(db, valkey_client, agent, watch_paths, new_version)

    return _agent_to_response(agent)


def rescan_agent(
    db: Session,
    valkey_client: Any,
    agent_id: str,
    force: bool,
    user_id: int,
) -> None:
    """
    Fuerza re-scan de baseline del agente.

    D-C14-03: si force=False y hay pending → raise PendingEventsExist(count=N).
    Si force=True → marcar pending como superseded y publicar rescan_baseline.
    """
    from app.modules.agents.streams import publish_rescan_baseline
    from app.modules.audit.models import AuditLog
    from app.modules.events.models import Event, EventStatus

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    # Contar eventos pending del agente
    pending_events = db.exec(
        select(Event).where(
            Event.agent_id == agent_id,
            Event.status == EventStatus.pending,
        )
    ).all()

    if not force and pending_events:
        raise PendingEventsExist(count=len(pending_events))

    # force=True: marcar pending como superseded
    if pending_events:
        for event in pending_events:
            event.status = EventStatus.superseded
            event.parent_event_id = None  # rescan, no cadena natural (D-C14-03)
            db.add(event)
        db.flush()

    # Registrar audit_log
    audit = AuditLog(
        user_id=user_id,
        action="agent_rescan",
        target_type="agent",
        detail=f'{{"agent_id": "{agent_id}", "force": {str(force).lower()}, "superseded_count": {len(pending_events)}}}',
    )
    db.add(audit)
    db.commit()

    # Publicar rescan_baseline post-commit
    publish_rescan_baseline(db, valkey_client, agent)


def _validate_csr(csr_pem: str, expected_agent_id: str) -> None:
    try:
        csr = x509.load_pem_x509_csr(csr_pem.encode())
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid CSR PEM")

    if not isinstance(csr.public_key(), Ed25519PublicKey):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSR must use Ed25519 key",
        )

    cn_attrs = csr.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    if not cn_attrs or cn_attrs[0].value != expected_agent_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSR CN does not match agent_id",
        )
