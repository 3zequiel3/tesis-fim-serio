from datetime import datetime
from enum import Enum

from pydantic import BaseModel, field_validator
from sqlalchemy import JSON, Column, UniqueConstraint
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
    shared_secret_hex: str | None = Field(default=None)  # persiste tras bootstrap para HMAC
    watch_paths: list[str] = Field(default=[], sa_column=Column(JSON))


class RevokedCertificate(SQLModel, table=True):
    __tablename__ = "revoked_certificates"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(foreign_key="agents.agent_id", index=True)
    serial_number: str
    revoked_at: datetime = Field(default_factory=datetime.utcnow)
    reason: str | None = Field(default=None)


class AgentRegisterRequest(BaseModel):
    agent_id: str
    bootstrap_secret: str

    @field_validator("bootstrap_secret")
    @classmethod
    def secret_min_length(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("bootstrap_secret must be at least 16 characters")
        return v


class AgentBootstrapRequest(BaseModel):
    agent_id: str
    csr_pem: str
    bootstrap_secret: str


class AgentBootstrapResponse(BaseModel):
    cert_pem: str
    ca_cert_pem: str
    shared_secret_hex: str
    master_secret_hex: str


class AgentResponse(BaseModel):
    """Schema de respuesta para un agente individual (GET /agents y GET /agents/{id})."""

    agent_id: str
    status: AgentStatus
    last_heartbeat: datetime | None
    queue_pressure: float | None
    ruleset_version_applied: int
    watch_paths: list[str]


class AgentListResponse(BaseModel):
    """Schema de respuesta para la lista de agentes (GET /agents)."""

    items: list[AgentResponse]
    total: int


class AgentConfigRequest(BaseModel):
    """Body para POST /agents/{id}/config."""

    watch_paths: list[str]


class AgentRescanRequest(BaseModel):
    """Body para POST /agents/{id}/rescan."""

    force: bool = False


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
