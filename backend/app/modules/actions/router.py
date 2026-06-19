"""
Router de acciones de aprobación/rechazo (C13).

Endpoints:
  POST /actions/approve       — aprueba un evento pending
  POST /actions/reject        — rechaza un evento pending
  POST /actions/bulk-approve  — aprueba múltiples eventos
  POST /actions/bulk-reject   — rechaza múltiples eventos

Todos requieren JWT de admin (require_admin).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import require_admin
from app.core.valkey import get_valkey_client
from app.modules.auth.models import User
from app.modules.actions.schemas import (
    ActionResponse,
    ApproveRequest,
    BulkApproveRequest,
    BulkRejectRequest,
    BulkResultResponse,
    RejectRequest,
)
from app.modules.actions.service import (
    AbsentConfirmationRequired,
    ConflictError,
    _approve_single,
    _reject_single,
    approve_bulk,
    reject_bulk,
)

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/approve", response_model=ActionResponse)
async def approve_event(
    body: ApproveRequest,
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
    current_user: User = Depends(require_admin),
) -> ActionResponse:
    """Aprueba un evento pending. Requiere JWT admin."""
    try:
        event = _approve_single(
            db=session,
            valkey_client=valkey_client,
            event_id=body.event_id,
            version=body.version,
            confirm_absent=body.confirm_absent,
            user_id=current_user.id,  # type: ignore[arg-type]
        )
    except AbsentConfirmationRequired:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "absent_confirmation_required"},
        )
    except ConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "detail": "event already modified or not pending"},
        )
    return ActionResponse(event_id=event.id, status="approved")  # type: ignore[arg-type]


@router.post("/reject", response_model=ActionResponse)
async def reject_event(
    body: RejectRequest,
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
    current_user: User = Depends(require_admin),
) -> ActionResponse:
    """Rechaza un evento pending. Requiere JWT admin."""
    try:
        event = _reject_single(
            db=session,
            valkey_client=valkey_client,
            event_id=body.event_id,
            version=body.version,
            action=body.action,
            user_id=current_user.id,  # type: ignore[arg-type]
        )
    except ConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "conflict", "detail": "event already modified or not pending"},
        )
    return ActionResponse(event_id=event.id, status="rejected")  # type: ignore[arg-type]


@router.post("/bulk-approve", response_model=BulkResultResponse)
async def bulk_approve_events(
    body: BulkApproveRequest,
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
    current_user: User = Depends(require_admin),
) -> BulkResultResponse:
    """Aprueba múltiples eventos. Resultado parcial por ítem. Requiere JWT admin."""
    items = [
        {"event_id": item.event_id, "version": item.version, "confirm_absent": item.confirm_absent}
        for item in body.items
    ]
    result = approve_bulk(
        db=session,
        valkey_client=valkey_client,
        items=items,
        user_id=current_user.id,  # type: ignore[arg-type]
    )
    return BulkResultResponse(**result)


@router.post("/bulk-reject", response_model=BulkResultResponse)
async def bulk_reject_events(
    body: BulkRejectRequest,
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
    current_user: User = Depends(require_admin),
) -> BulkResultResponse:
    """Rechaza múltiples eventos. Resultado parcial por ítem. Requiere JWT admin."""
    items = [
        {"event_id": item.event_id, "version": item.version, "action": item.action.value}
        for item in body.items
    ]
    result = reject_bulk(
        db=session,
        valkey_client=valkey_client,
        items=items,
        user_id=current_user.id,  # type: ignore[arg-type]
    )
    return BulkResultResponse(**result)
