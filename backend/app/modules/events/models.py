from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel


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
    parent_event_id: int | None = Field(default=None, foreign_key="events.id")
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
