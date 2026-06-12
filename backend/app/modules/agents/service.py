"""
Lógica de negocio para registro y bootstrap de agentes FIM (Change 06).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

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
