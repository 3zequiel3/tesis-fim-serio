"""
Schemas Pydantic para el módulo actions (C13 — approve/reject).

ApproveRequest / RejectRequest: operaciones unitarias.
BulkApproveRequest / BulkRejectRequest: operaciones en lote.
ActionResponse / BulkResultResponse: respuestas.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class RejectAction(str, Enum):
    restore = "restore"
    quarantine = "quarantine"


class ReleaseMode(str, Enum):
    """How a quarantine is released (D83/RN-177)."""

    restore_original = "restore_original"
    restore_baseline = "restore_baseline"
    discard = "discard"


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


# ── Quarantine release (D83/RN-177) ───────────────────────────────────────────


class ReleaseQuarantineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: ReleaseMode
    # Mandatory operator justification (audit only; never sent to the agent).
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ReleaseQuarantineResponse(BaseModel):
    event_id: int
    command_id: str
    mode: ReleaseMode
    ack_status: str  # always "pending": the outcome arrives through command_ack
