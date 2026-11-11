## Context

La change cierra cinco defectos del backend detectados en las revisiones del 2026-11-11 y verificados contra `devel` `30efcaf` (ver `proposal.md`). Todos son de validación de entrada o de semántica de seguridad; ninguno toca el agente, el modelo de datos ni los streams. Las decisiones normativas ya están cerradas en los appendices: D89/RN-183 (cambio de contraseña), D90/RN-184 (cuerpo de error), D91/RN-185 (rutas), D92/RN-186 (rate limit del login).

Estado actual relevante:

- `rules/service.py:109` `validate_pattern` lanza `ValueError` con texto en inglés; los routers lo traducen a `HTTPException(422, detail=str(exc))` (`rules/router.py:88,144`). `create_rule` también lanza `ValueError("duplicate pattern: ...")`.
- `agents/service.py:147` `update_agent_config(watch_paths)` persiste, incrementa `ruleset_version`, audita y encola `update_config` sin validar.
- `events/router.py:169` `Event.path.startswith(path_prefix)`.
- `core/rate_limit.py:37` `check_login_rate_limit` hace `INCR` + `EXPIRE NX` y lanza 429 si `count > max`; el router lo llama antes de verificar (`auth/router.py:100`). El docstring defiende contar antes «para evitar timing oracle».
- uvicorn arranca sin `--forwarded-allow-ips` (`backend/Dockerfile:75`), así que `request.client.host` es el par TCP: el contenedor `nginx` del frontend, que ya envía `X-Forwarded-For $proxy_add_x_forwarded_for` y `X-Real-IP` (`frontend/nginx/common-locations.conf:11-12`). El puerto 8000 se publica sólo en `127.0.0.1` (`docker-compose.yml:321`).
- `core/security.py:85` `password_policy_error` devuelve mensajes en inglés y la usan `change-password` y el alta de admins (C20).

## Goals / Non-Goals

**Goals:**

- Rechazar con `422` y código estable toda ruta mal formada antes de persistir o publicar.
- Que el rate limit del login proteja contra fuerza bruta sin permitir que un tercero bloquee al `admin` desde otro origen.
- Mensajes en español con `{code, message}` en los endpoints tocados, contrato fijado por tests.
- Cada defecto con un test que falla sin el arreglo.

**Non-Goals:**

- Reescribir todos los `detail` string del backend (sólo los endpoints tocados; D90/RN-184 admite la forma heredada).
- Un handler global de excepciones o un esquema de errores en OpenAPI.
- Verificar la existencia de rutas vigiladas en el backend (es del agente, D36/RN-130).
- Revalidar o migrar reglas y `watch_paths` existentes.
- Cambiar la emisión de tokens del cambio de contraseña (D89/RN-183 la mantiene revocada).
- Tocar el frontend: lo adapta la Change 72.

## Decisions

### D-1 · Un módulo puro de validación de rutas

`backend/app/core/path_validation.py`, sin dependencias de FastAPI ni de la base:

```python
class PathValidationError(ValueError):
    def __init__(self, code: str, message: str, index: int | None = None): ...

MAX_PATH_LENGTH = 1024
MAX_WATCH_PATHS = 64

def validate_rule_pattern(pattern: str) -> None: ...
def validate_watch_paths(paths: list[str]) -> None: ...
```

Orden de chequeo de una ruta (el primero que falla decide el código): vacío/espacios → no absoluto → segmento `..` (`".." in body.split("/")`) → carácter de control (`any(ord(c) < 0x20 or ord(c) == 0x7F for c in s)`) → largo. Para un patrón, después, el glob. `PathValidationError` hereda de `ValueError` para que los `except ValueError` existentes sigan atrapándolo mientras se migran los routers.

*Alternativa descartada*: validadores Pydantic en los modelos de request. Producirían la lista de errores de Pydantic (forma c de D90/RN-184), sin `code` estable, y el `PUT /rules/{id}` usa un modelo distinto del alta: la validación quedaría duplicada.

*Alternativa descartada*: `posixpath.normpath(p) != p`. Rechazaría `//` o `/./`, que el agente tolera y que no son un riesgo; el defecto es `..`, que sale de la raíz declarada.

### D-2 · Glob bien formado con la regla de clases de `fnmatch`

`fnmatch.translate` nunca falla: un `[` sin cierre se trata como literal. El chequeo replica su escaneo de clases: al ver `[`, se salta un `!` inicial y un `]` inmediato (que en `fnmatch` es literal dentro de la clase) y se busca el `]` de cierre; si no existe, `pattern_invalid_glob`. Así `[]abc]`, `[!.]` y `[a-z]` son válidos y `/etc/[` no. Se testea contra el propio `fnmatch.fnmatch` para fijar que todo patrón aceptado con clase se comporta como clase.

### D-3 · Duplicados de `watch_paths` sin la barra final

Se compara `p.rstrip("/") or "/"`. `"/etc"` y `"/etc/"` son la misma marca de fanotify en el agente; dos entradas iguales producirían eventos duplicados. El `index` reportado es el de la segunda aparición.

### D-4 · Traducción a HTTP en los routers

Los routers de reglas y agentes atrapan `PathValidationError` y responden `HTTPException(422, detail={"code": e.code, "message": e.message} | ({"index": e.index} if e.index is not None else {}))`. El duplicado de regla pasa a `PathValidationError("pattern_duplicate", ...)` desde `create_rule`/`update_rule`. Los mensajes son frases cortas en español neutro, p. ej. «El patrón debe ser una ruta absoluta (empezar con /).».

### D-5 · `path_prefix` con `autoescape=True`

`Event.path.startswith(path_prefix, autoescape=True)`: SQLAlchemy escapa `%`, `_` y el carácter de escape `/` y agrega la cláusula `ESCAPE` portable. Se verifica con un test sobre PostgreSQL real (el harness de la suite) porque el escape depende del dialecto.

### D-6 · Rate limit: tres operaciones explícitas

`core/rate_limit.py` reemplaza `check_login_rate_limit` por:

- `login_retry_after(username, ip) -> int | None`: `GET` del contador; si `>= max`, devuelve `max(1, TTL)` (`TTL` de la key; si es `-1`, aplica `EXPIRE NX` y devuelve la ventana).
- `record_failed_login(username, ip) -> None`: `INCR` + `EXPIRE window NX` (preserva M1).
- `clear_login_attempts(username, ip) -> None`: `DEL`.

El router: resolver IP → `login_retry_after` (429 si corresponde) → buscar usuario y verificar → fallo: `record_failed_login` + 401 → `is_active` → éxito: `clear_login_attempts`. El docstring deja de afirmar que contar antes evita un oráculo: el oráculo no existe porque un intento bloqueado responde 429 sin evaluar la contraseña, y uno no bloqueado tarda lo mismo (Argon2id) acierte o no. `check_api_rate_limit` no cambia.

*Alternativa descartada*: mantener `INCR` previo y decrementar en éxito. Un éxito concurrente con fallos podría dejar el contador negativo o borrar fallos ajenos; el `DEL` en éxito es la semántica pedida («reinicio en éxito») y no deja estados intermedios.

*Alternativa descartada*: un tope adicional sólo por `username`. Reintroduce el bloqueo global de `admin` desde cualquier origen, que es el defecto.

### D-7 · IP real en el backend, no en uvicorn

`core/client_ip.py` con `client_ip(request, trusted: list[IPv4Network | IPv6Network]) -> str`. Se recorre `X-Forwarded-For` de derecha a izquierda descartando entradas de confianza y valores que no parsean como IP; la primera no confiable es el cliente. `Settings.trusted_proxy_cidrs: list[IPv4Network | IPv6Network]` con validador que acepta CSV y nombra la entrada inválida.

*Alternativa descartada*: `uvicorn --proxy-headers --forwarded-allow-ips=<cidrs>`. Reescribe `request.client` para toda la app (logs, ticket SSE, auditoría) y su soporte de CIDR depende de la versión; un helper explícito acota el efecto al login y es testeable sin levantar uvicorn.

*Alternativa descartada*: confiar en `X-Real-IP`. Es más simple, pero no hay garantía de que todo proxy delante del backend lo sobrescriba; `X-Forwarded-For` con recorrido desde la derecha es el estándar y cubre cadenas de proxies.

Los compose fijan `TRUSTED_PROXY_CIDRS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` en el servicio `backend`: la red `fim_internal` es un bridge con subred asignada por Docker dentro de esos rangos.

### D-8 · Cambio de contraseña: reutilización y mensajes

En `users/router.py`, tras verificar `current_password` y la política, `verify_password(body.new_password, user.password_hash)` → 422 `password_reuse`. Se evalúa después de la política para que una contraseña débil reciba primero el mensaje de política. `password_policy_error` pasa a devolver `(code, message)`; el alta de admins (C20) usa el mismo mensaje. La revocación (`router.py:78-100`) no cambia.

### D-9 · Mensajes y README

Los mensajes siguen el registro que ya usa la consola (voseo, como `frontend/src/pages/ForcePasswordChange.tsx`), porque el frontend los muestra tal cual. Login: `invalid_credentials` «Usuario o contraseña incorrectos.», `account_disabled` «La cuenta está deshabilitada.», `login_rate_limited` «Demasiados intentos fallidos. Esperá unos minutos e intentá de nuevo.». El README (sección de rate limit, ~línea 489) se actualiza con el mensaje nuevo y la semántica de fallidos e IP real.

## Risks / Trade-offs

- [El frontend actual muestra `detail` como string y vería un objeto] → la Change 72 depende de ésta y lo resuelve con `readApiError`. Entre ambas, la consola puede mostrar mensajes genéricos; no se despliega esta change sola para la demo.
- [Un compose personalizado sin `TRUSTED_PROXY_CIDRS`] → el default de loopback hace que todos los clientes compartan la IP del `nginx`: vuelve el riesgo de bloqueo global, pero sólo tras cinco **fallos**. Se documenta en `.env.example`.
- [Un peer local que alcanza `127.0.0.1:8000` aparece con IP privada de confianza y puede falsear `X-Forwarded-For`] → riesgo residual aceptado en D92/RN-186: ese actor ya tiene acceso al host.
- [NAT compartido con el operador] → un tercero detrás de la misma IP pública puede bloquearlo 15 minutos con cinco fallos; aceptado en D92/RN-186.
- [Reglas existentes inválidas siguen activas] → no se revalidan; la consola las sigue mostrando y pueden editarse (la edición sí valida).
- [Tests que crean reglas relativas o asertan textos en inglés] → se adaptan, uno por uno, con nota en el commit.

## Migration Plan

Sin migración de datos. Despliegue: actualizar imagen del backend y los compose (variable nueva). Rollback: volver a la imagen anterior; la variable `TRUSTED_PROXY_CIDRS` se ignora en versiones previas.

## Open Questions

Ninguna. Todas las suposiciones nuevas quedaron cerradas en D89–D92 / RN-183–RN-186.
