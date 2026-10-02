## ADDED Requirements

### Requirement: Volumen aislado para la clave de envoltura del secreto de agente (D86/RN-180)

El compose SHALL declarar el volumen nombrado `backend_secrets`, montado en `certs-init` (lectura y
escritura) y en `backend` (sólo lectura, `:ro`) en `/secrets`. Ningún otro servicio —en particular
el contenedor `agent` de laboratorio, `frontend`, `valkey`, `db` y `n8n`— MUST montarlo. La clave de
envoltura MUST NOT ubicarse en `backend_certs`, que el contenedor `agent` de laboratorio monta en
`docker-compose.yml`, `docker-compose.acceptance-lab.yml` y `docker-compose.us02-us20-us31-lab.yml`.

`certs-init` y `backend` SHALL recibir `AGENT_SECRET_WRAP_KEY_PATH` con default
`/secrets/agent-secret-wrap.key`. `certs-init` SHALL generar la clave según la spec
`agent-secret-at-rest` como paso adicional, después de los certificados; si ese paso falla,
`certs-init` SHALL terminar con exit distinto de 0 y `backend` no SHALL arrancar. Los compose de
laboratorio que definen su propio `backend` sin `certs-init` SHALL proveer un paso equivalente que
genere la clave antes de que `backend` arranque.

#### Scenario: Volumen vacío
- **WHEN** se ejecuta `up --profile app` con `backend_secrets` vacío
- **THEN** `certs-init` termina con exit 0 y existe `/secrets/agent-secret-wrap.key` con modo `0400`
- **AND** `backend` arranca y su lifespan carga la clave

#### Scenario: El agente de laboratorio no ve la clave
- **WHEN** se renderiza la composición con `--profile app --profile lab`
- **THEN** el servicio `agent` no monta `backend_secrets`
- **AND** sólo `certs-init` y `backend` lo montan

#### Scenario: Montaje de sólo lectura en el backend
- **WHEN** se inspecciona el servicio `backend` en la composición renderizada
- **THEN** `backend_secrets` está montado en `/secrets` con modo `ro`
