## ADDED Requirements

### Requirement: Modelo PublishedCommand

El sistema SHALL definir un modelo `PublishedCommand` (tabla `published_commands`) en `backend/app/modules/rules/models.py` (owner C12 por D10). El modelo MUST tener las columnas: `id: int` (PK autoincrement), `command_type: str`, `target_agent_id: str | None`, `ruleset_version: int`, `published_at: datetime`. La tabla MUST quedar registrada en `SQLModel.metadata` para que `create_all()` la incluya. Esta tabla es el registro histórico de todo comando versionado publicado al stream `commands` y la base del check D5 de "agente al día".

#### Scenario: Tabla creada en create_all
- **WHEN** el backend arranca y ejecuta `SQLModel.metadata.create_all(engine)`
- **THEN** la tabla `published_commands` existe con las columnas id, command_type, target_agent_id, ruleset_version, published_at

#### Scenario: Inserción de un comando publicado
- **WHEN** se inserta un `PublishedCommand` con `command_type='rule_sync'`, `target_agent_id='agent-1'`, `ruleset_version=5`
- **THEN** la fila persiste con un `id` autoincrement y un `published_at` no nulo

#### Scenario: target_agent_id nullable
- **WHEN** se define el modelo `PublishedCommand`
- **THEN** `target_agent_id` admite `None` para soportar el check D5 (`... OR target_agent_id IS NULL`), aunque `rule_sync` siempre lo escribe con id explícito
