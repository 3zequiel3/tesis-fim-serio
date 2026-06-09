from datetime import datetime

from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id")
    action: str
    target_type: str | None = Field(default=None)
    target_id: int | None = Field(default=None)
    detail: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
