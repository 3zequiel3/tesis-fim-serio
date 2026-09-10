from datetime import datetime, timezone
from enum import Enum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

# D39/RN-133: ver events/models.py — mismo motivo, mismo patrón.
_TZ_AWARE = sa.DateTime(timezone=True)


class AlertSeverity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class AlertChannel(str, Enum):
    n8n = "n8n"
    smtp_fallback = "smtp_fallback"
    webhook_fallback = "webhook_fallback"
    log_only = "log_only"


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="events.id")
    severity: AlertSeverity
    channel: AlertChannel | None = Field(default=None)
    delivered_at: datetime | None = Field(default=None, sa_type=_TZ_AWARE)
    failed_at: datetime | None = Field(default=None, sa_type=_TZ_AWARE)
    last_error: str | None = Field(default=None)
    retry_count: int = Field(default=0)
    # Durable notification state. notification_id is minted before the first
    # network attempt and remains stable across automatic and manual retries.
    notification_id: str | None = Field(default=None, index=True, unique=True)
    attempt_count: int = Field(default=0)
    next_retry_at: datetime | None = Field(default=None, sa_type=_TZ_AWARE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=_TZ_AWARE)
