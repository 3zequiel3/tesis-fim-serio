# Spec delta: backend-core

## MODIFIED Requirements

### Requirement: Lifespan FastAPI ejecuta create_all + seed_admin idempotentes (D3, RN-62, RN-76)

El sistema SHALL declarar el lifespan de FastAPI en `app/main.py` usando `@asynccontextmanager` que, en startup, ejecute `SQLModel.metadata.create_all(engine)` y `seed_admin()` (en ese orden), y en shutdown emita un log de cierre. La función `seed_admin()` SHALL estar definida en `backend/app/modules/auth/service.py` (no en `main.py`) y SHALL ser importada desde allí. La función `seed_admin()` SHALL ser idempotente: si ya existe un admin en la tabla `users`, SHALL retornar sin hacer nada. Si el modelo `User` ya está registrado en el metadata (Change 03 mergeado), SHALL crear el usuario con las credenciales de las variables de entorno `ADMIN_USERNAME` / `ADMIN_PASSWORD`, hasheado con Argon2id, con `must_change_password=True`. Si la tabla `users` no existe todavía, SHALL retornar temprano emitiendo un log `info` con `reason="users_table_not_yet_created"`. NO SHALL existir un servicio `db-init` en `docker-compose.yml` (D3).

#### Scenario: Backend arranca sin tablas en M1
- **WHEN** se ejecuta `docker compose --profile app up backend` en un entorno donde la base `fim` está vacía y ningún modelo SQLModel está registrado
- **THEN** el contenedor llega a estado `running`
- **AND** el lifespan termina sin excepción
- **AND** los logs incluyen una línea con `event=seed_admin.skipped` y `reason=users_table_not_yet_created`

#### Scenario: seed_admin crea el primer admin cuando User está disponible
- **WHEN** el backend arranca con Change 03 mergeado y la tabla `users` vacía
- **THEN** `seed_admin()` crea exactamente un usuario con `username=ADMIN_USERNAME` y `must_change_password=True`
- **AND** el password almacenado es el hash Argon2id del `ADMIN_PASSWORD` del `.env`

#### Scenario: seed_admin es idempotente
- **WHEN** el backend se reinicia con la tabla `users` ya conteniendo el admin
- **THEN** `seed_admin()` no crea un segundo usuario
- **AND** no modifica el usuario existente

#### Scenario: create_all es idempotente
- **WHEN** el backend se reinicia con la base ya inicializada por un arranque previo
- **THEN** `SQLModel.metadata.create_all(engine)` no lanza error
- **AND** no recrea ni borra tablas existentes
