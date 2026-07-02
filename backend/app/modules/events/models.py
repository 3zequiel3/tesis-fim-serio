from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.modules.rules.models import RuleSeverity


class EventStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    auto_restored = "auto_restored"
    quarantined = "quarantined"
    alert_only = "alert_only"
    superseded = "superseded"


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    event_id: str = Field(unique=True, index=True)  # UUID v4 del agente (dedup RN-73)
    agent_id: str = Field(foreign_key="agents.agent_id", index=True)
    path: str = Field(index=True)
    hash_detected: str
    status: EventStatus = Field(index=True)
    # D34/RN-128 (C38): severidad calculada al ingerir con la lógica compartida
    # de D-C15-01 (rules/service.py::determine_severity_for_path). Snapshot al
    # momento de la ingesta — cambios posteriores del ruleset no re-etiquetan.
    severity: RuleSeverity = Field(default=RuleSeverity.low, index=True)
    # D33/RN-127 (C39): symlink-as-object. is_symlink distingue un evento sobre
    # un symlink (nunca se sigue el link) de uno sobre un archivo regular;
    # symlink_target es el string crudo de os.readlink, sin normalizar.
    is_symlink: bool = Field(default=False)
    symlink_target: str | None = Field(default=None)
    parent_event_id: int | None = Field(
        default=None,
        sa_column=sa.Column(sa.Integer, sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
    )
    version: int = Field(default=0)
    process_pid: int | None = Field(default=None)
    process_uid: int | None = Field(default=None)
    process_exe: str | None = Field(default=None)
    detected_at: datetime
    received_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = Field(default=None)
    resolved_by: int | None = Field(default=None, foreign_key="users.id")


class RejectionReason(str, Enum):
    clock_skew = "clock_skew"
    invalid_schema = "invalid_schema"
    invalid_signature = "invalid_signature"
    unknown_agent = "unknown_agent"
    duplicate_event = "duplicate_event"
    rate_limited = "rate_limited"


class RejectedEventAudit(SQLModel, table=True):
    __tablename__ = "rejected_events_audit"

    id: int | None = Field(default=None, primary_key=True)
    event_id: str | None = Field(default=None)
    agent_id: str
    reason: RejectionReason
    received_at: datetime
    detected_at: datetime | None = Field(default=None)
    payload_dump: str
