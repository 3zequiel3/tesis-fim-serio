from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel


class RuleAction(str, Enum):
    auto_restore = "auto_restore"
    quarantine = "quarantine"
    manual_review = "manual_review"
    alert_only = "alert_only"


class RuleSeverity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class Rule(SQLModel, table=True):
    __tablename__ = "rules"

    id: int | None = Field(default=None, primary_key=True)
    pattern: str
    severity: RuleSeverity
    action: RuleAction
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RulesetVersion(SQLModel, table=True):
    __tablename__ = "ruleset_versions"

    id: int | None = Field(default=None, primary_key=True)
    version: int = Field(default=0)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PublishedCommand(SQLModel, table=True):
    """Outbox de comandos versionados hacia el stream commands (D9, D10, H6).

    Para el fan-out `rule_sync` (H6), la fila se inserta como `pending` con el
    payload firmado completo en la MISMA transacción que avanza `Rule` +
    `RulesetVersion`; un background task (`publish_pending_commands`) hace el
    `XADD` de forma diferida con retry y marca la fila `published` al
    confirmar. Esto garantiza que un fallo de Valkey no pierda el comando ni
    deje la versión avanzada sin comando entregable.

    El resto de los comandos (baseline_update, restore_file, quarantine_file —
    C13/D10) se siguen insertando como `published` de forma síncrona, sin
    pasar por el outbox — su publicación ya ocurre post-commit del evento.
    """

    __tablename__ = "published_commands"

    id: int | None = Field(default=None, primary_key=True)
    command_type: str
    target_agent_id: str | None = Field(default=None)
    ruleset_version: int
    payload: str = Field(default="")
    status: str = Field(default="published", index=True)  # "pending" | "published"
    published_at: datetime | None = Field(default=None)
