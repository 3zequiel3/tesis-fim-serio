from datetime import datetime, timezone
from enum import Enum

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

# D39/RN-133: toda columna de instante declara su zona explícitamente (timestamptz),
# de modo que create_all (backend/tests/conftest.py:80) fabrique el mismo tipo que
# la migración 011. Ver D-2 del design de timestamps-timezone-aware.
_TZ_AWARE = sa.DateTime(timezone=True)

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
    # US-09: baseline hash plus bounded unified diff; complete file versions are not stored.
    hash_expected: str | None = Field(default=None, max_length=64)
    diff_text: str | None = Field(default=None, sa_column=sa.Column(sa.Text, nullable=True))
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
    # D35/RN-129 (C40): true cuando la acción automática (auto_restore/quarantine)
    # falló en el agente. Ortogonal al status — un pending con action_failed=true
    # significa que el archivo sigue adulterado Y la remediación ya falló.
    action_failed: bool = Field(default=False)
    # D36/RN-130 (C41): causa del fallo de acción, vocabulario cerrado del lado
    # del agente (read_only_mount, permission_denied, no_baseline_content, ...).
    # Sin validación contra enum en el backend (tolerancia hacia adelante, mismo
    # criterio que action/is_symlink): un valor desconocido se persiste tal cual.
    action_error: str | None = Field(default=None, max_length=64)
    parent_event_id: int | None = Field(
        default=None,
        sa_column=sa.Column(sa.Integer, sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
    )
    version: int = Field(default=0)
    process_pid: int | None = Field(default=None)
    process_uid: int | None = Field(default=None)
    process_exe: str | None = Field(default=None)
    detected_at: datetime = Field(sa_type=_TZ_AWARE)
    received_at: datetime = Field(sa_type=_TZ_AWARE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=_TZ_AWARE)
    resolved_at: datetime | None = Field(default=None, sa_type=_TZ_AWARE)
    resolved_by: int | None = Field(default=None, foreign_key="users.id")


class RejectionReason(str, Enum):
    clock_skew = "clock_skew"
    invalid_schema = "invalid_schema"
    invalid_signature = "invalid_signature"
    unknown_agent = "unknown_agent"
    duplicate_event = "duplicate_event"
    rate_limited = "rate_limited"
    # D37/RN-131: enmienda de invalid_schema. schema_version PARSEABLE pero
    # mayor al soportado — el agente va adelantado, el payload es válido y
    # el backend todavía no sabe leerlo. Nack RETENIBLE (con retry_after),
    # a diferencia de invalid_schema que sigue siendo terminal.
    schema_version_unsupported = "schema_version_unsupported"


class RejectedEventAudit(SQLModel, table=True):
    __tablename__ = "rejected_events_audit"

    id: int | None = Field(default=None, primary_key=True)
    event_id: str | None = Field(default=None)
    agent_id: str
    reason: RejectionReason
    received_at: datetime = Field(sa_type=_TZ_AWARE)
    detected_at: datetime | None = Field(default=None, sa_type=_TZ_AWARE)
    payload_dump: str
