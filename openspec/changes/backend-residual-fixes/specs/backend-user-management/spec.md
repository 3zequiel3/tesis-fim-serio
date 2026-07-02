## ADDED Requirements

### Requirement: User tiene un campo email real, único y validado (D29, RN-44)

El modelo `User` (`backend/app/modules/auth/models.py`) MUST tener un campo `email` persistente, `NOT NULL` y `UNIQUE`. La creación de usuarios (`CreateUserRequest`) MUST validar el email con `EmailStr` (rechazando cadenas que no sean emails válidos), y las respuestas (`UserItem` / `UserListResponse`) MUST devolver el `email` real del usuario — no el `username` como sustituto. La columna MUST agregarse vía script SQL idempotente en `backend/db/migrations/` (D3, sin Alembic), siguiendo el prefijo numérico secuencial (`002_...` tras `001_add_agent_status_revoked.sql`).

#### Scenario: Crear usuario con email válido
- **WHEN** un admin hace `POST /users` con un `email` sintácticamente válido y una password válida
- **THEN** el sistema crea el usuario con ese `email` persistido y responde 201 con el `email` real del nuevo usuario

#### Scenario: Email inválido rechazado
- **WHEN** `POST /users` se llama con un `email` que no es un email válido (p. ej. `"noesunmail"`)
- **THEN** el sistema responde 422 con un error de validación de `EmailStr`

#### Scenario: Email duplicado rechazado por UNIQUE
- **WHEN** `POST /users` se llama con un `email` que ya existe en la tabla `users`
- **THEN** el sistema responde 409 (violación de constraint UNIQUE)

#### Scenario: Listado devuelve el email real
- **WHEN** un admin hace `GET /users`
- **THEN** cada item devuelve el `email` real persistido del usuario, no su `username`

#### Scenario: Migración idempotente de la columna email
- **WHEN** el script SQL que agrega la columna `email` se ejecuta dos veces
- **THEN** la segunda ejecución no produce error (uso de `IF NOT EXISTS` o equivalente idempotente)

### Requirement: Seed admin con email configurable vía ADMIN_EMAIL (D3, D29)

El seed del admin inicial (ejecutado en el lifespan de FastAPI, D3) MUST asignar al usuario admin un `email` tomado de la variable de entorno `ADMIN_EMAIL`, con default `admin@fim.local` cuando la variable no está definida. El seed MUST ser idempotente: re-ejecutarlo no debe fallar si el admin ya existe.

#### Scenario: Seed admin usa ADMIN_EMAIL
- **WHEN** el backend arranca con `ADMIN_EMAIL=ops@example.com` y no existe admin previo
- **THEN** el admin sembrado tiene `email = "ops@example.com"`

#### Scenario: Seed admin usa el default
- **WHEN** el backend arranca sin `ADMIN_EMAIL` definido y no existe admin previo
- **THEN** el admin sembrado tiene `email = "admin@fim.local"`

#### Scenario: Seed idempotente con admin existente
- **WHEN** el backend arranca y el admin ya existe en la tabla `users`
- **THEN** el seed no falla ni duplica el usuario
