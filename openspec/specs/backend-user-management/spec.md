# backend-user-management Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: Admin can list all admin users (RN-45)
The system SHALL allow an authenticated admin to retrieve a paginated list of all admin users. Password hashes MUST NOT be returned in any response.

#### Scenario: Admin lists users
- **WHEN** an authenticated admin sends GET /users
- **THEN** system returns a paginated list with user id, email, and created_at for each user

#### Scenario: Unauthenticated request rejected
- **WHEN** a request without a valid session token is sent to GET /users
- **THEN** system returns 401

#### Scenario: Non-admin request rejected
- **WHEN** a request from a non-admin user is sent to GET /users
- **THEN** system returns 403

### Requirement: Admin can create an additional admin user (RN-45)
The system SHALL allow an authenticated admin to create a new admin account. The new password SHALL be hashed with Argon2id. Every creation SHALL be recorded in the audit_log.

#### Scenario: Successful admin creation
- **WHEN** an authenticated admin sends POST /users with a valid email and password
- **THEN** system creates the user, records an audit_log entry with action "user_created", and returns 201 with the new user's id and email

#### Scenario: Duplicate email rejected
- **WHEN** POST /users is called with an email that already exists in the system
- **THEN** system returns 409

#### Scenario: Weak password rejected
- **WHEN** POST /users is called with a password shorter than the minimum length
- **THEN** system returns 422 with a validation error

#### Scenario: Creation recorded in audit log
- **WHEN** an admin successfully creates a new user via POST /users
- **THEN** an audit_log entry is written with actor_id of the requesting admin and target_id of the new user

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

