## ADDED Requirements

### Requirement: Un único lector de errores de la API

El frontend SHALL leer todo error HTTP con una única función `readApiError(err)` en `frontend/src/api/errors.ts`, que devuelve `{status, code, message, data}` a partir de las tres formas de `detail` de D90/RN-184: string (→ `message`), objeto `{code, message?, ...}` (→ `code`, `message`, y los campos extra en `data`) y lista de Pydantic (→ `message` con el primer `msg`). Un error sin respuesta (red) MUST producir `status = 0` y un mensaje en español sobre la conexión. Ningún componente, hook ni toast MUST leer `err.response.data` directamente ni interpolar un valor que no sea string. Los mocks de tests de errores MUST usar la forma real del backend (`{"detail": ...}`).

#### Scenario: Código anidado en detail
- **WHEN** la respuesta es `422` con `{"detail": {"code": "absent_confirmation_required"}}`
- **THEN** `readApiError` devuelve `code = "absent_confirmation_required"`

#### Scenario: Campo extra del detalle
- **WHEN** la respuesta es `409` con `{"detail": {"code": "pending_events_exist", "count": 3}}`
- **THEN** `readApiError` devuelve `code = "pending_events_exist"` y `data.count = 3`

#### Scenario: Lista de validación de Pydantic
- **WHEN** la respuesta es `422` con `{"detail": [{"loc": ["body", "pattern"], "msg": "Field required", "type": "missing"}]}`
- **THEN** `readApiError` devuelve un `message` string y nunca `[object Object]`

#### Scenario: Error de red
- **WHEN** la request falla sin respuesta
- **THEN** `readApiError` devuelve `status = 0` y un mensaje en español sobre la conexión

### Requirement: El bundle se divide por ruta

Cada página enrutada en `frontend/src/App.tsx` SHALL cargarse con `React.lazy` dentro de un `Suspense` con el estado de carga del sistema de diseño. `Login`, `ForcePasswordChange` y el layout pueden quedar en el chunk inicial. El chunk JavaScript inicial de `pnpm build` MUST pesar menos de 250 kB sin comprimir (hoy un único chunk de 515 kB) (D93/RN-187).

#### Scenario: Las páginas se cargan bajo demanda
- **WHEN** se ejecuta `pnpm build`
- **THEN** la salida contiene un chunk por cada página enrutada y el chunk de entrada pesa menos de 250 kB

### Requirement: Lint obligatorio con configuración plana

El frontend SHALL tener `frontend/eslint.config.js` (configuración plana de ESLint 9) con `@eslint/js` recomendado, `typescript-eslint` recomendado con verificación de tipos sobre `src/`, `eslint-plugin-react-hooks` (`rules-of-hooks` como error y `exhaustive-deps` como error) y `eslint-plugin-react-refresh`. `package.json` SHALL exponer `"lint": "eslint ."` y `pnpm lint` MUST terminar sin errores. Una regla sólo puede desactivarse por línea con un comentario que explique el motivo (D93/RN-187).

#### Scenario: Lint limpio
- **WHEN** se ejecuta `pnpm lint` en `frontend/`
- **THEN** termina con código 0 y sin errores

### Requirement: Dependencias de producción sin vulnerabilidades altas

`pnpm audit --prod --audit-level high` SHALL terminar con código 0. En particular, `axios` MUST ser ≥ 1.20.0 (con su `follow-redirects` corregido) y `react-router-dom`/`react-router` ≥ 7.18.2. Si una vulnerabilidad alta no tiene versión corregida, MUST resolverse con un `pnpm.overrides` documentado en `package.json` o declararse en `design.md` con su justificación (D93/RN-187).

#### Scenario: Auditoría limpia
- **WHEN** se ejecuta `pnpm audit --prod --audit-level high` en `frontend/`
- **THEN** termina con código 0
