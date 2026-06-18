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
    """Registro histórico de comandos versionados publicados al stream commands (D10)."""

    __tablename__ = "published_commands"

    id: int | None = Field(default=None, primary_key=True)
    command_type: str
    target_agent_id: str | None = Field(default=None)
    ruleset_version: int
    published_at: datetime = Field(default_factory=datetime.utcnow)
