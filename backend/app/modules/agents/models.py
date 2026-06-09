from datetime import datetime
from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class AgentStatus(str, Enum):
    online = "online"
    offline = "offline"
    draining = "draining"
    dead = "dead"


class Agent(SQLModel, table=True):
    __tablename__ = "agents"

    agent_id: str = Field(primary_key=True)
    status: AgentStatus = Field(default=AgentStatus.offline)
    last_heartbeat: datetime | None = Field(default=None)
    ruleset_version_applied: int = Field(default=0)
    queue_pressure: float | None = Field(default=None)
    bootstrap_secret_hash: str | None = Field(default=None)


class RevokedCertificate(SQLModel, table=True):
    __tablename__ = "revoked_certificates"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(foreign_key="agents.agent_id", index=True)
    serial_number: str
    revoked_at: datetime = Field(default_factory=datetime.utcnow)
    reason: str | None = Field(default=None)


class BaselineStatus(str, Enum):
    present = "present"
    absent = "absent"


class BaselineEntry(SQLModel, table=True):
    __tablename__ = "baseline_entries"
    __table_args__ = (UniqueConstraint("path", "agent_id"),)

    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(index=True)
    agent_id: str = Field(foreign_key="agents.agent_id", index=True)
    hash: str | None = Field(default=None)
    status: BaselineStatus
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    ruleset_version: int
