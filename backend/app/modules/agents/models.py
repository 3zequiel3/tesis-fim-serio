from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, field_validator
from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

# D39/RN-133: ver events/models.py — mismo motivo, mismo patrón.
_TZ_AWARE = DateTime(timezone=True)


class AgentStatus(str, Enum):
    online = "online"
    offline = "offline"
    draining = "draining"
    dead = "dead"
    revoked = "revoked"


class Agent(SQLModel, table=True):
    __tablename__ = "agents"

    agent_id: str = Field(primary_key=True)
    status: AgentStatus = Field(default=AgentStatus.offline)
    # D68/RN-162: instante de registro, no nulo. Referencia temporal para
    # agentes que nunca latieron (last_heartbeat IS NULL) — ver
    # _sweep_offline en heartbeat_consumer.py. Migración 019.
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=_TZ_AWARE)
    last_heartbeat: datetime | None = Field(default=None, sa_type=_TZ_AWARE)
    ruleset_version_applied: int = Field(default=0)
    queue_pressure: float | None = Field(default=None)
    # US-21: cantidad de eventos en la cola local del agente, tal como la
    # reporta el heartbeat (agent/heartbeat.py, clave "queue_size"). Nullable
    # sin default, mismo criterio que discarded_events (D37/RN-131): None =
    # "el agente nunca reportó", distinto de 0 = "reportó cola vacía".
    # Migración 015.
    queue_size: int | None = Field(default=None)
    bootstrap_secret_hash: str | None = Field(default=None)
    shared_secret_hex: str | None = Field(default=None)  # persiste tras bootstrap para HMAC
    watch_paths: list[str] = Field(default=[], sa_column=Column(JSON))
    # D36/RN-130 (C41): mapa {watch_path: clasificación} reportado por el
    # preflight de escritura del agente en cada heartbeat (writable |
    # read_only_mount | permission_denied | missing). Mismo precedente de
    # columna JSON que watch_paths. Nullable: un agente que nunca reportó
    # (viejo, o sin heartbeat aún) queda en None, no en {} — {} se leería
    # como "todos los paths escribibles".
    watch_path_status: dict[str, str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # D37/RN-131: contador acumulativo (desde el arranque del proceso del
    # agente) de eventos descartados localmente por el publicador — techo de
    # reintentos agotado, o nack terminal (invalid_schema/clock_skew).
    # Nullable sin default: None = "el agente nunca reportó" (agente sin
    # actualizar a D37, o sin heartbeat todavía), deliberadamente distinto
    # de 0 = "reportó y no descartó nada". Migración 010.
    discarded_events: int | None = Field(default=None)
    # D69/RN-163: contador acumulativo de eventos descartados por caer fuera
    # de los watch_paths (marca de fanotify de filesystem completo en modo
    # FID, D46/RN-140). El agente ya publica esta clave en cada heartbeat
    # desde antes de esta columna; acá sólo empieza a persistirse. Nullable
    # sin default, mismo criterio que discarded_events: None = "el agente
    # nunca reportó", distinto de 0 = "reportó y no descartó nada". A
    # diferencia de discarded_events, un positivo acá es **esperado**, no una
    # anomalía. Migración 020.
    out_of_scope_drops: int | None = Field(default=None)
    # D72/RN-166: booleano calculado por el agente (una sola lectura de
    # queue_pressure contra el umbral de 0.8, W3/RN-84) y persistido tal cual.
    # Nullable sin default: None = "el agente nunca reportó la clave",
    # deliberadamente distinto de False = "reportó y no hay presión".
    # Migración 021.
    queue_pressure_high: bool | None = Field(default=None)


class RevokedCertificate(SQLModel, table=True):
    __tablename__ = "revoked_certificates"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(foreign_key="agents.agent_id", index=True)
    serial_number: str
    revoked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=_TZ_AWARE)
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


class AgentRenewRequest(BaseModel):
    agent_id: str


class AgentRenewResponse(BaseModel):
    cert_pem: str
    ca_cert_pem: str


class AgentResponse(BaseModel):
    """Schema de respuesta para un agente individual (GET /agents y GET /agents/{id})."""

    agent_id: str
    status: AgentStatus
    last_heartbeat: datetime | None
    queue_pressure: float | None
    # US-21: cantidad de eventos en la cola local del agente. None si el
    # agente nunca reportó heartbeat (distinto de 0).
    queue_size: int | None = None
    ruleset_version_applied: int
    watch_paths: list[str]
    # D36/RN-130 (C41): mapa por-path de clasificación de escritura, tal como
    # lo persistió el consumer de heartbeat. None si el agente nunca reportó.
    watch_path_status: dict[str, str] | None = None
    # D37/RN-131: contador acumulativo de eventos descartados localmente por
    # el agente, tal como lo persistió el consumer de heartbeat. None si el
    # agente nunca reportó — distinto de 0.
    discarded_events: int | None = None
    # D69/RN-163: contador acumulativo de descartes fuera de scope, tal como
    # lo persistió el consumer de heartbeat. None si el agente nunca reportó
    # — distinto de 0. Un positivo es esperado (a diferencia de
    # discarded_events, que es siempre anómalo).
    out_of_scope_drops: int | None = None
    # D72/RN-166: flag de presión de cola calculado por el agente, tal como
    # lo persistió el consumer de heartbeat. None si el agente nunca reportó
    # la clave — distinto de False.
    queue_pressure_high: bool | None = None


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
    # US-22: selección de paths específicos para el rescan. None/[] = todos
    # los watch_paths del agente (comportamiento previo, retrocompatible).
    paths: list[str] | None = None


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
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=_TZ_AWARE)
    ruleset_version: int
