# Spec delta: backend-core

## ADDED Requirements

### Requirement: Middleware CORS con validación de Origin (RN-95, D7)

El sistema SHALL registrar un middleware CORS en `backend/app/main.py` que valide el header `Origin` de cada request contra una whitelist configurable. La whitelist SHALL leerse de la variable de entorno `CORS_ALLOWED_ORIGINS` (lista separada por comas, ej. `http://localhost:5173,https://fim.internal`). Si `Origin` no está en la whitelist, la request SHALL ser rechazada con 403. En ausencia de la variable `CORS_ALLOWED_ORIGINS`, la whitelist SHALL ser vacía y el backend SHALL rechazar toda request con `Origin` presente (seguro por defecto). Las requests sin header `Origin` (ej. curl, herramientas internas) SHALL pasar sin restricción.

#### Scenario: Origin en whitelist es aceptado
- **WHEN** se hace una request con `Origin: http://localhost:5173`
- **AND** `CORS_ALLOWED_ORIGINS` incluye `http://localhost:5173`
- **THEN** la response incluye `Access-Control-Allow-Origin: http://localhost:5173`
- **AND** el código de respuesta del endpoint es el esperado (200, 201, etc.)

#### Scenario: Origin fuera de whitelist es rechazado
- **WHEN** se hace una request con `Origin: http://evil.example.com`
- **AND** ese dominio no está en `CORS_ALLOWED_ORIGINS`
- **THEN** la response es 403

#### Scenario: Request sin Origin pasa sin restricción
- **WHEN** se hace una request HTTP sin header `Origin`
- **THEN** la request procede normalmente (el CORS middleware no interfiere)

#### Scenario: CORS_ALLOWED_ORIGINS vacía — toda request con Origin rechazada
- **WHEN** la variable `CORS_ALLOWED_ORIGINS` no está definida o es vacía
- **AND** se hace una request con cualquier `Origin`
- **THEN** la response es 403

### Requirement: Conexión Valkey disponible en el lifespan para módulos de auth

El sistema SHALL establecer una conexión Valkey (`valkey.Valkey`) durante el lifespan de FastAPI, disponible para inyección como dependency (`get_valkey_client() -> valkey.Valkey`). La conexión SHALL usar `settings.VALKEY_URL` y SHA ser singleton (una instancia compartida por el proceso). En shutdown, el lifespan SHALL cerrar la conexión explícitamente.

#### Scenario: get_valkey_client disponible durante el lifetime de la app
- **WHEN** un endpoint llama `Depends(get_valkey_client)`
- **THEN** recibe una instancia de `valkey.Valkey` con conexión activa al servicio Valkey

#### Scenario: Shutdown cierra la conexión
- **WHEN** la app recibe señal de shutdown
- **THEN** el lifespan cierra el cliente Valkey sin excepción
