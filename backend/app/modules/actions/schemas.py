"""
Schemas Pydantic para el módulo actions (C13 — approve/reject).

ApproveRequest / RejectRequest: operaciones unitarias.
BulkApproveRequest / BulkRejectRequest: operaciones en lote.
ActionResponse / BulkResultResponse: respuestas.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


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


class BulkApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_ids: list[int]


class BulkRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_ids: list[int]
    action: RejectAction


class BulkResultResponse(BaseModel):
    succeeded: list[int]
    failed: list[dict]
