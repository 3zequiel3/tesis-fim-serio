from datetime import datetime, timezone

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

# D39/RN-133: ver events/models.py — mismo motivo, mismo patrón.
_TZ_AWARE = sa.DateTime(timezone=True)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    role: str = Field(default="admin")
    is_active: bool = Field(default=True)
    must_change_password: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=_TZ_AWARE)
