## ADDED Requirements

### Requirement: El script de preparación escribe la ruta de la clave de envoltura (D86/RN-180)

`scripts/prepare_server_env.py` SHALL escribir `AGENT_SECRET_WRAP_KEY_PATH=/secrets/agent-secret-wrap.key`
en el `.env` generado, junto a las rutas canónicas de certificados. El script MUST NOT generar ni
escribir la clave misma: la clave vive en el volumen `backend_secrets` y la genera `certs-init` (spec
`agent-secret-at-rest`). `.env.example` SHALL documentar la variable con el mismo valor.

#### Scenario: Ruta presente en el `.env` generado
- **WHEN** se ejecuta el script en un servidor nuevo
- **THEN** el `.env` contiene `AGENT_SECRET_WRAP_KEY_PATH=/secrets/agent-secret-wrap.key`
- **AND** no contiene ningún valor de 32 bytes asociado a la clave de envoltura

#### Scenario: Renderización sin warnings
- **WHEN** se renderiza `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app config` con el `.env` generado
- **THEN** no hay warnings de variables faltantes
