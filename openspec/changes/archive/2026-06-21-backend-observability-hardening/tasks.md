## 1. Users module — schemas

- [x] 1.1 Agregar `UserListResponse` a `backend/app/modules/users/schemas.py`: lista paginada con `id`, `email`, `created_at` (sin password_hash)
- [x] 1.2 Agregar `CreateUserRequest` a `backend/app/modules/users/schemas.py`: campos `email: str` y `password: str` con validación de longitud mínima

## 2. Users module — endpoints

- [x] 2.1 Agregar `GET /users` en `backend/app/modules/users/router.py`: protegido con `require_admin`; retorna `UserListResponse` paginado; no incluye password_hash
- [x] 2.2 Agregar `POST /users` en `backend/app/modules/users/router.py`: protegido con `require_admin`; hashea password con `hash_password` (Argon2id); crea usuario; escribe `audit_log` con `action="user_created"`, `actor_id` del admin solicitante, `target_id` del nuevo usuario; retorna 201 con id y email
- [x] 2.3 Manejar 409 en POST /users cuando el email ya existe (IntegrityError de la DB)
- [x] 2.4 Registrar router de users en `backend/app/main.py` si no está ya incluido

## 3. Rate limit — migración a config

- [x] 3.1 Agregar settings `RATE_LIMIT_LOGIN_PER_MINUTE`, `RATE_LIMIT_API_PER_MINUTE`, `RATE_LIMIT_EVENTS_PER_MINUTE` en `backend/app/core/config.py` con defaults idénticos a las constantes hardcodeadas actuales
- [x] 3.2 Reemplazar constantes hardcodeadas en `backend/app/core/rate_limit.py` por referencias a `settings.RATE_LIMIT_*`
- [x] 3.3 Documentar las nuevas variables en `docs/operations.md` con sus valores default

## 4. Tests — users endpoints

- [x] 4.1 Crear `backend/tests/modules/users/test_user_management.py`
- [x] 4.2 Test: admin puede listar usuarios via GET /users; respuesta no contiene password_hash
- [x] 4.3 Test: non-admin recibe 403 en GET /users
- [x] 4.4 Test: admin crea nuevo usuario via POST /users; verifica 201 y registro en audit_log
- [x] 4.5 Test: POST /users con email duplicado retorna 409
- [x] 4.6 Test: POST /users con password corto retorna 422
- [x] 4.7 Agregar skip condicional en Windows sin psycopg (patrón consistente con C08+)

## 5. Tests — rate limiter carga

- [x] 5.1 Crear `backend/tests/core/test_rate_limit_load.py`
- [x] 5.2 Test: N requests dentro del bucket no son rechazados (status 200/expected)
- [x] 5.3 Test: N+1 requests en la misma ventana temporal retornan 429
- [x] 5.4 Test: ventana se resetea tras expirar el intervalo

## 6. Tests — verificación retención y compactación (C11)

- [x] 6.1 Crear `backend/tests/modules/events/test_retention.py`
- [x] 6.2 Test: `retention_task()` elimina eventos terminales con `created_at` > 30d; eventos referenciados en `audit_log` no se eliminan (RN-98)
- [x] 6.3 Test: `compact_chain()` compacta cadenas de longitud > 10 correctamente
- [x] 6.4 Usar fixtures con override explícito de `created_at` (no sleep para evitar flakiness)
- [x] 6.5 Agregar skip condicional en Windows sin psycopg

## 7. Workflows n8n

- [x] 7.1 Crear `n8n/workflows/slack_alert.json`: webhook trigger recibe payload de alerta FIM; nodo HTTP Request POST a Slack webhook; incluir severity y path en el mensaje
- [x] 7.2 Crear `n8n/workflows/email_alert.json`: webhook trigger; nodo Send Email con asunto y cuerpo formateados con datos de la alerta
- [x] 7.3 Crear `n8n/workflows/ticketing_alert.json`: webhook trigger; nodo HTTP Request a Jira/Linear con creación de issue incluyendo severity, path y event_id
- [x] 7.4 Documentar en los headers de cada JSON la versión de n8n (2.16.1) y las credenciales requeridas para importar

## 8. Documentación operativa

- [x] 8.1 Crear `docs/operations.md` con sección "Variables de entorno requeridas": listar todas las env vars con tipo, default y descripción (incluyendo las nuevas `RATE_LIMIT_*`)
- [x] 8.2 Agregar sección "Formato de logs estructurados": campos fijos (timestamp, level, trace_id, module, message), ejemplo JSON, nivel de log configurable
- [x] 8.3 Agregar sección "Retención de datos": política de 30d para eventos terminales (RN-98), qué se preserva (referenciados en audit_log), cómo se configura el job
- [x] 8.4 Agregar sección "Instalación del agente como systemd unit": unit file de ejemplo, comandos de enable/start/status, permisos CAP_SYS_ADMIN requeridos
- [x] 8.5 Agregar referencia a `docs/operations.md` en el README principal del repositorio
