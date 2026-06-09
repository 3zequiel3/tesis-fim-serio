## Context

Change 02 dejó `backend/app/modules/` vacío. Sin modelos SQLModel registrados, `create_all()` no crea tablas y ningún change posterior (03-auth, 08-events, 11-ingestion, etc.) puede implementarse. Este change es el único que toca el schema de datos: define todos los modelos antes de que cualquier lógica de negocio los consuma.

Las decisiones de diseño relevantes (D1-D6) ya fueron cerradas en Abril 2026 y viven en los appendices de `docs/arquitectura_stack.md` y `docs/reglas_de_negocio.md`. Este design doc resume las implicancias de layout y las decisiones que afectan cómo se organizan los módulos.

## Goals / Non-Goals

**Goals:**
- Definir todos los modelos SQLModel con `table=True`, sus enums canónicos, relaciones FK y constraints.
- Establecer la estructura de archivos de `modules/` para que los changes de lógica tengan dónde aterrizar.
- Garantizar que `SQLModel.metadata.create_all(engine)` crea el schema completo al arrancar.
- Formalizar el modelo `User` (ya usado como placeholder en `seed_admin`) con todos sus campos.

**Non-Goals:**
- Lógica de negocio, servicios, routers, consumers — van en los changes que usan los modelos.
- Migraciones versionadas (Alembic) — no en scope hasta que se introduzca en un change de hardening.
- Modelos del agente FIM — son independientes y viven en `agent/`.

## Decisions

### Layout: un archivo `models.py` por módulo de dominio

Cada módulo de `backend/app/modules/<domain>/models.py` contiene los modelos del dominio. Los enums importados entre módulos van en el módulo que los posee (e.g., `EventStatus` en `events/models.py`; `BaselineStatus` en `agents/models.py`).

La alternativa de un solo `models.py` en `core/` simplifica las importaciones pero acumula todos los modelos en un archivo de 400+ líneas que hace más costoso el review de cada change. Módulo por módulo es preferible porque los changes futuros modifican un solo módulo a la vez.

### `main.py` importa explícitamente todos los módulos antes de `create_all()`

SQLModel/SQLAlchemy solo registra modelos cuyas clases ya están importadas cuando se llama `create_all()`. La convención habitual es usar un módulo `backend/app/models.py` que importa todo. Aquí se prefiere importar directamente en `main.py` (o en un bloque `__init__.py` del paquete `modules/`) para mantener visibilidad explícita de qué tablas existen.

### Enums como `str, Enum` con valores en minúscula snake_case (RN-71)

Todos los enums son `class Foo(str, Enum)`. Esto permite que SQLModel los serialice como strings en PostgreSQL sin un tipo `Enum` nativo, lo que simplifica la recreación del schema en dev (no hay tipos custom que recrear). Los valores siguen el léxico canónico en minúsculas (RN-71).

### `Event.hash` renombrado a `Event.hash_detected` (consistencia con docs)

El campo que guarda el SHA-256 al momento de detección se llama `hash_detected` (como en el pseudocódigo de `arquitectura_stack.md §935`). Esto evita colisión con la built-in `hash()` de Python y deja claro que es el hash capturado por fanotify, no el hash de referencia del baseline.

### FK entre módulos: `Agent.agent_id` como PK string, no int auto-increment

El `agent_id` es un string UUID generado por el agente al hacer bootstrap (RN-63). Usar un PK string evita la necesidad de un mapeo `int → UUID` en la tabla. Los índices sobre strings cortos (UUID sin guiones, 32 chars) son eficientes en PostgreSQL.

### `AuditLog` sin FK a `Event`

El `audit_log` registra cualquier acción admin (aprobación, rechazo, CRUD de reglas, config de agente). Forzar una FK a `events` haría imposible auditar operaciones que no involucran un evento (e.g., crear una regla). El campo `target_id: int | None` + `target_type: str` cubre el polimorfismo sin FK.

## Risks / Trade-offs

- **Riesgo: schema drift entre dev y prod** → En este sistema single-instance (RN-76), `create_all()` + drop del volumen en dev es suficiente. Si en el futuro se agrega Alembic, el trigger está documentado en D3.
- **Riesgo: ciclos de importación entre módulos** → Minimizado por la regla "cada módulo solo importa de `core/`". Si un modelo referencia una FK de otro módulo, importa solo el string de `__tablename__`, no la clase.
- **Trade-off: `str, Enum` vs PostgreSQL native Enum** → Los PostgreSQL Enum son más eficientes en storage pero requieren `ALTER TYPE` para agregar valores. Con `str, Enum` se puede agregar un valor al Enum Python y hacer `create_all()` sin error; el constraint viene del código, no del DB. Aceptable para el ciclo de desarrollo de tesis.

## Migration Plan

No hay migración: `create_all()` en el lifespan crea todas las tablas la primera vez. En entornos dev existentes (change 02 mergeado), se debe hacer `docker compose down -v && docker compose up` para recrear el volumen con el schema completo.
