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
    """Outbox de comandos versionados hacia el stream commands (D9, D10, H6) +
    tracking de ejecución confirmada por el agente (D30/RN-124, C36).

    Para el fan-out `rule_sync` (H6), la fila se inserta como `pending` con el
    payload firmado completo en la MISMA transacción que avanza `Rule` +
    `RulesetVersion`; un background task (`publish_pending_commands`) hace el
    `XADD` de forma diferida con retry y marca la fila `published` al
    confirmar. Esto garantiza que un fallo de Valkey no pierda el comando ni
    deje la versión avanzada sin comando entregable.

    El resto de los comandos (baseline_update, restore_file, quarantine_file —
    C13/D10) se siguen insertando como `published` de forma síncrona, sin
    pasar por el outbox — su publicación ya ocurre post-commit del evento.

    **Dos columnas de estado con semánticas distintas y ortogonales (D-1 del
    design de C36 — NO fusionar ni confundir):**
      - `status` (`"pending" | "published"`): estado de **outbox** — si el
        `XADD` a Valkey ya se ejecutó (H6/D9/D10). Preexistente, sin cambios.
      - `ack_status` (`"pending" | "acked" | "failed" | "timeout" | None`):
        estado de **ejecución** — si el agente confirmó el comando vía
        `command_ack` (stream `event_ack`). `None` para comandos que el
        agente no confirma (p. ej. `rule_sync`, excluido del barrido de
        timeout).

    Ambas columnas comparten el literal `"pending"` con significados
    distintos: `status=pending` = por-publicar a Valkey; `ack_status=pending`
    = publicado, esperando confirmación de ejecución del agente.
    """

    __tablename__ = "published_commands"

    id: int | None = Field(default=None, primary_key=True)
    command_type: str
    target_agent_id: str | None = Field(default=None)
    event_id: int | None = Field(default=None, index=True)  # D-1bis: correlación Event -> ack_status
    ruleset_version: int
    payload: str = Field(default="")
    status: str = Field(default="published", index=True)  # outbox: "pending" | "published"
    published_at: datetime | None = Field(default=None)

    # Tracking de ejecución (D30/RN-124, C36) — ver docstring arriba.
    command_id: str | None = Field(default=None, unique=True, index=True)
    ack_status: str | None = Field(default=None)  # "pending" | "acked" | "failed" | "timeout"
    acked_at: datetime | None = Field(default=None)
    error: str | None = Field(default=None)
