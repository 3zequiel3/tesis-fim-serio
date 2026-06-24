## ADDED Requirements

### Requirement: Tarea de renovación proactiva de certificado mTLS

El agente SHALL ejecutar una tarea asyncio en background (`_cert_renewal_loop` en `agent/__main__.py`) que arranca junto con el loop principal solo si los certificados ya fueron bootstrapped. La tarea MUST verificar la vigencia del certificado de cliente cada `cert_renewal_check_interval_h` horas (configurable en `agent/config.py`, default `24.0`). El intervalo de espera MUST usar `asyncio.sleep` y MUST poder interrumpirse al activarse el `stop_event` del agente para no bloquear el shutdown (RN-111, D13).

#### Scenario: Loop arranca solo con certificados bootstrapped

- **WHEN** el agente arranca y `certs_dir` contiene un certificado de cliente válido
- **THEN** la tarea `_cert_renewal_loop` se registra entre las corrutinas del loop principal

#### Scenario: Loop no arranca sin bootstrap

- **WHEN** el agente arranca sin certificado bootstrapped (caso de primer arranque ya cubierto por el flujo de bootstrap)
- **THEN** la renovación no se ejecuta hasta que exista un certificado de cliente

#### Scenario: Intervalo de chequeo configurable

- **WHEN** la configuración define `cert_renewal_check_interval_h: 6.0`
- **THEN** la tarea verifica la vigencia del certificado cada 6 horas

### Requirement: Renovación gatillada por umbral de 15 días

La tarea de renovación SHALL leer `not_valid_after` del certificado de cliente actual y, si el certificado vence en 15 días o menos, MUST iniciar la renovación. Si el certificado vence en más de 15 días, la tarea MUST registrar el chequeo en nivel debug y no realizar ninguna llamada de red (RN-111, D13).

#### Scenario: Certificado vence dentro de 15 días — renovación gatillada

- **WHEN** el chequeo periódico detecta que el certificado vence en 10 días
- **THEN** el agente inicia una solicitud de renovación a `POST /agents/renew`

#### Scenario: Certificado vigente — sin renovación

- **WHEN** el chequeo periódico detecta que el certificado vence en 60 días
- **THEN** el agente no realiza ninguna llamada de red y continúa esperando el próximo intervalo

### Requirement: Renovación vía mTLS contra POST /agents/renew

El agente SHALL solicitar la renovación a `POST <backend_url>/agents/renew` usando una conexión mTLS que presenta el certificado de cliente actual y su clave privada, verificando la CA local (`ca.pem`). El agente MUST NOT reusar el `bootstrap_secret` (de un solo uso). Ante una respuesta exitosa con un nuevo certificado, el agente MUST persistir el certificado con escritura atómica (archivo temporal + `os.replace`) y permisos `0600` en `certs_dir`. Las nuevas conexiones Valkey tras reconexión usarán el certificado renovado (RN-111, D13).

#### Scenario: Renovación exitosa persiste el nuevo certificado

- **WHEN** `POST /agents/renew` responde 200 con un certificado nuevo válido y firmado por la CA
- **THEN** el agente escribe atómicamente el nuevo certificado en `certs_dir` con permisos `0600`

#### Scenario: Conexión mTLS usa el certificado actual como client cert

- **WHEN** el agente llama a `/agents/renew`
- **THEN** la solicitud presenta el certificado de cliente actual y la CA local como verificación, sin enviar `bootstrap_secret`

### Requirement: Degradación tolerante a fallos de renovación

Si la renovación falla por cualquier causa (endpoint inexistente, error de red, respuesta no 200, certificado inválido), el agente SHALL registrar una advertencia (`log.warning`) y MUST continuar la operación normal, reintentando en el próximo intervalo de chequeo. Un fallo de renovación MUST NOT interrumpir el detector, el publisher, el heartbeat ni el loop principal (RN-111, D13).

#### Scenario: Endpoint no existe en el backend

- **WHEN** `POST /agents/renew` responde 404 (backend sin el endpoint implementado)
- **THEN** el agente registra un warning y reintenta en el próximo intervalo sin interrumpir ninguna otra tarea

#### Scenario: Error de red durante la renovación

- **WHEN** la conexión a `/agents/renew` falla con un error de transporte
- **THEN** el agente captura la excepción, registra un warning y conserva el certificado actual intacto

#### Scenario: Certificado de respuesta inválido — no se sobreescribe

- **WHEN** la respuesta de renovación contiene un certificado que no se puede cargar o no está firmado por la CA
- **THEN** el agente descarta la respuesta, registra un warning y conserva el certificado actual sin modificar el archivo
