"""
Schemas Pydantic para el módulo actions (C13 — approve/reject).

ApproveRequest / RejectRequest: operaciones unitarias.
BulkApproveRequest / BulkRejectRequest: operaciones en lote.
ActionResponse / BulkResultResponse: respuestas.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class RejectAction(str, Enum):
    restore = "restore"
    quarantine = "quarantine"


# ── Single operations ─────────────────────────────────────────────────────────


class ApproveRequest(BaseModel):
    event_id: int
    version: int
    confirm_absent: bool = False


class RejectRequest(BaseModel):
    event_id: int
    version: int
    action: RejectAction


class ActionResponse(BaseModel):
    event_id: int
    status: str  # "approved" | "rejected"
    # M8: solo relevante en reject — true si hubo no-op por baseline "absent"
    # (RN-74); no altera el comportamiento del no-op, solo lo hace observable.
    baseline_absent: bool = False


# ── Bulk operations ───────────────────────────────────────────────────────────


class BulkApproveItem(BaseModel):
    event_id: int
    version: int
    confirm_absent: bool = False


class BulkApproveRequest(BaseModel):
    items: list[BulkApproveItem]


class BulkRejectItem(BaseModel):
    event_id: int
    version: int
    action: RejectAction


class BulkRejectRequest(BaseModel):
    items: list[BulkRejectItem]


class BulkResultResponse(BaseModel):
    succeeded: list[int]
    failed: list[dict]
    # M8: solo poblado por reject_bulk — event_id -> baseline_absent.
    # approve_bulk lo deja vacío (no aplica).
    baseline_absent: dict[int, bool] = {}
