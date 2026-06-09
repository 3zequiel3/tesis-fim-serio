from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel


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
    delivered_at: datetime | None = Field(default=None)
    failed_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None)
    retry_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
