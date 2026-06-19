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
