"""
Endpoints REST del dominio de reglas (Change 12).

POST   /rules        — crear regla (admin)
GET    /rules        — listar reglas ordenadas por severity (autenticado)
GET    /rules/{id}   — obtener regla por id (autenticado)
PUT    /rules/{id}   — actualizar regla (admin)
DELETE /rules/{id}   — eliminar regla (admin)
"""

from __future__ import annotations

from datetime import datetime

import valkey as _valkey_pkg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import require_admin, require_full_access
from app.core.valkey import get_valkey_client
from app.modules.auth.models import User
from app.modules.rules.models import RuleAction, RuleSeverity
from app.modules.rules.service import (
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    update_rule,
)

router = APIRouter(prefix="/rules", tags=["rules"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class RuleCreate(BaseModel):
    pattern: str
    severity: RuleSeverity
    action: RuleAction


class RuleUpdate(BaseModel):
    pattern: str
    severity: RuleSeverity
    action: RuleAction


class RuleOut(BaseModel):
    id: int
    pattern: str
    severity: RuleSeverity
    action: RuleAction
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule_endpoint(
    body: RuleCreate,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
    valkey_client: _valkey_pkg.Valkey = Depends(get_valkey_client),
) -> RuleOut:
    """Crea una regla. Restringido a admin (RN-29). Retorna 201."""
    try:
        rule = create_rule(
            session,
            valkey_client,
            admin.id,  # type: ignore[arg-type]
            {"pattern": body.pattern, "severity": body.severity.value, "action": body.action.value},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return RuleOut.model_validate(rule)


@router.get("", response_model=list[RuleOut])
async def list_rules_endpoint(
    _user: User = Depends(require_full_access),
    session: Session = Depends(get_session),
) -> list[RuleOut]:
    """Lista reglas ordenadas por severity canónico (RN-09). Requiere autenticación."""
    rules = list_rules(session)
    return [RuleOut.model_validate(r) for r in rules]


@router.get("/{rule_id}", response_model=RuleOut)
async def get_rule_endpoint(
    rule_id: int,
    _user: User = Depends(require_full_access),
    session: Session = Depends(get_session),
) -> RuleOut:
    """Obtiene una regla por id. 404 si no existe."""
    rule = get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return RuleOut.model_validate(rule)


@router.put("/{rule_id}", response_model=RuleOut)
async def update_rule_endpoint(
    rule_id: int,
    body: RuleUpdate,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
    valkey_client: _valkey_pkg.Valkey = Depends(get_valkey_client),
) -> RuleOut:
    """Actualiza una regla. Restringido a admin. 404 si no existe, 422 si inválido."""
    try:
        rule = update_rule(
            session,
            valkey_client,
            admin.id,  # type: ignore[arg-type]
            rule_id,
            {"pattern": body.pattern, "severity": body.severity.value, "action": body.action.value},
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return RuleOut.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule_endpoint(
    rule_id: int,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
    valkey_client: _valkey_pkg.Valkey = Depends(get_valkey_client),
) -> None:
    """Elimina una regla. Restringido a admin. 404 si no existe. Retorna 204."""
    delete_rule(
        session,
        valkey_client,
        admin.id,  # type: ignore[arg-type]
        rule_id,
    )
