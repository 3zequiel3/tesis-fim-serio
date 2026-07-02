## MODIFIED Requirements

### Requirement: Comando baseline_update publicado en Valkey al aprobar

Al aprobar exitosamente un evento, el sistema SHALL publicar en el stream `commands` de Valkey un mensaje con los campos: `type="baseline_update"`, `command_id` (UUID v4), `event_id`, `target_agent_id` (igual a `event.agent_id`), `path` (igual a `event.path`), `hash` (igual a `event.hash`, puede ser null), `baseline_status` ("present" | "absent"), `ruleset_version` (counter global incrementado, D5), `issued_at` (ISO8601 UTC), `signature` (HMAC-SHA256 hex del payload canónico con la clave `shared_secret` del agente). NO se publica ningún comando `get_file_hash` (D2, D8).

La publicación en Valkey MUST ejecutarse DESPUÉS de `db.commit()` — la transacción de PostgreSQL MUST ser durable antes de que el agente reciba el comando. El orden en `_approve_single` SHALL ser: (1) verificar hash/confirm_absent; (2) UPDATE optimista; (3) flush + refresh; (4) `_increment_ruleset_version`; (5) `_upsert_baseline_entry`; (6) `_write_audit`; (7) `db.commit()`; (8) `db.refresh(event)`; (9) `publish_baseline_update` (FIX-02).

#### Scenario: Comando baseline_update contiene los campos requeridos
- **WHEN** se aprueba un evento exitosamente
- **THEN** el mensaje en el stream `commands` contiene exactamente los campos `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `hash`, `baseline_status`, `ruleset_version`, `issued_at`, `signature`
- **AND** `signature` verifica correctamente con HMAC-SHA256 y el `shared_secret` del agente objetivo

#### Scenario: Publicación en Valkey ocurre después del commit
- **WHEN** se aprueba un evento exitosamente
- **THEN** el mensaje `baseline_update` se publica en Valkey únicamente después de que `db.commit()` completó
- **AND** si el proceso falla entre `db.commit()` y la publicación, la DB tiene el estado correcto

#### Scenario: No se publica get_file_hash
- **WHEN** se procesa cualquier approve o reject
- **THEN** no aparece ningún mensaje de tipo `get_file_hash` en el stream `commands`

---

### Requirement: Comandos restore_file / quarantine_file publicados en Valkey al rechazar

Al rechazar exitosamente, el sistema SHALL publicar en el stream `commands` un mensaje con: `type="restore_file"` o `type="quarantine_file"`, `command_id` (UUID v4), `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`. No incluye `hash` ni `ruleset_version`.

La publicación en Valkey MUST ejecutarse DESPUÉS de `db.commit()`. El orden en `_reject_single` SHALL ser: (1) UPDATE optimista; (2) flush + refresh; (3) consultar `baseline_entry`; (4) `_write_audit`; (5) `db.commit()`; (6) `db.refresh(event)`; (7) `publish_restore_file` o `publish_quarantine_file` según corresponda (FIX-02).

#### Scenario: Comando restore_file contiene campos requeridos
- **WHEN** se rechaza con `action="restore"`
- **THEN** el mensaje en el stream contiene `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`
- **AND** la `signature` verifica con el `shared_secret` del agente

#### Scenario: Publicación en Valkey ocurre después del commit en reject
- **WHEN** se rechaza un evento exitosamente
- **THEN** el mensaje `restore_file` o `quarantine_file` se publica en Valkey únicamente después de que `db.commit()` completó
- **AND** si el proceso falla entre `db.commit()` y la publicación, la DB tiene el estado correcto (`status=rejected`)
