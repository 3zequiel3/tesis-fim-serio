from datetime import datetime, timezone

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

# D39/RN-133: ver events/models.py — mismo motivo, mismo patrón.
_TZ_AWARE = sa.DateTime(timezone=True)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    action: str
    target_type: str | None = Field(default=None)
    target_id: int | None = Field(default=None)
    detail: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=_TZ_AWARE)
