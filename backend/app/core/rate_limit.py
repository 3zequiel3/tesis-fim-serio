"""
Helpers de rate limiting con fixed-window en Valkey (D7, C20, M1, D92/RN-186).

Login: configurable via RATE_LIMIT_LOGIN_ATTEMPTS / RATE_LIMIT_LOGIN_WINDOW_SECONDS.
API autenticada: configurable via RATE_LIMIT_API_PER_MINUTE.

Defaults: 5 intentos / 15 min (login), 100 req/min (API).

Login (D92/RN-186): cuenta SOLO intentos FALLIDOS por (usuario + IP real) en una
ventana FIJA (fixed-window, no sliding-window) de N segundos. Se expone como
tres operaciones explícitas:
  - `login_retry_after`: consulta (GET + TTL) sin incrementar; devuelve los
    segundos restantes si el (user+IP) está bloqueado, o None.
  - `record_failed_login`: INCR + EXPIRE NX tras un intento fallido.
  - `clear_login_attempts`: DEL tras un login exitoso (reinicio del contador).
Un login exitoso nunca incrementa. Un intento bloqueado responde 429 SIN evaluar
la contraseña, así que no existe un oráculo: un intento no bloqueado tarda lo
mismo (Argon2id) acierte o no. Pedidos simultáneos pueden superar el umbral en
a lo sumo la cantidad de pedidos en vuelo; se acepta.

M1: el TTL se fija con EXPIRE ... NX (nx=True) en CADA incremento. `NX`
aplica el TTL SOLO cuando la key todavía no tiene uno, con lo que:
  - el primer incremento de la ventana fija el TTL una única vez, y
  - los incrementos siguientes NO lo tocan.
Esto preserva la semántica fixed-window de N segundos (NO sliding-window):
un EXPIRE incondicional en cada incremento reescribiría el TTL y desplazaría
la ventana, que nunca expiraría mientras siguieran llegando requests.
Además es auto-reparador: si una key quedó sin TTL (p. ej. un INCR exitoso
seguido de un EXPIRE fallido), como no tiene expiry, el próximo EXPIRE NX la
repara sin intervención manual, evitando un lockout permanente del (user+IP).
`login_retry_after` aplica la misma reparación si encuentra una key sin TTL.

Las funciones usan el cliente Valkey async (get_async_valkey_client) para no
bloquear el event loop. El parámetro valkey_client es opcional para permitir
inyección en tests; si no se provee, se usa el singleton async.
"""

from fastapi import HTTPException

from app.core.config import settings

LOGIN_RL_PREFIX = "fim:rl:login:"
API_RL_PREFIX = "fim:rl:api:"


def _login_key(username: str, ip: str) -> str:
    return f"{LOGIN_RL_PREFIX}{username}:{ip}"


def _client(valkey_client):
    if valkey_client is not None:
        return valkey_client
    from app.core.valkey import get_async_valkey_client

    return get_async_valkey_client()


async def login_retry_after(username: str, ip: str, valkey_client=None) -> int | None:
    """Segundos hasta que (username, ip) pueda reintentar, o None si no está bloqueado."""
    valkey_client = _client(valkey_client)
    key = _login_key(username, ip)
    raw = await valkey_client.get(key)
    if raw is None or int(raw) < settings.rate_limit_login_attempts:
        return None
    window_seconds = settings.rate_limit_login_window_seconds
    ttl = await valkey_client.ttl(key)
    if ttl == -2:  # expiró entre el GET y el TTL
        return None
    if ttl < 0:  # -1: key sin TTL (EXPIRE perdido) — repararla, no bloquear para siempre
        await valkey_client.expire(key, window_seconds, nx=True)
        ttl = window_seconds
    return max(1, int(ttl))


async def record_failed_login(username: str, ip: str, valkey_client=None) -> None:
    """Suma un intento fallido; fija el TTL de la ventana una sola vez (EXPIRE NX)."""
    valkey_client = _client(valkey_client)
    key = _login_key(username, ip)
    await valkey_client.incr(key)
    # M1: EXPIRE ... NX — fija el TTL solo si la key no lo tiene. Preserva la
    # ventana fija (no la desliza) y auto-repara una key que quedó sin TTL.
    await valkey_client.expire(key, settings.rate_limit_login_window_seconds, nx=True)


async def clear_login_attempts(username: str, ip: str, valkey_client=None) -> None:
    """Borra el contador tras un login exitoso."""
    await _client(valkey_client).delete(_login_key(username, ip))


async def check_api_rate_limit(user_id: int, valkey_client=None) -> None:
    if valkey_client is None:
        from app.core.valkey import get_async_valkey_client
        valkey_client = get_async_valkey_client()
    max_requests = settings.rate_limit_api_per_minute
    window_seconds = 60
    key = f"{API_RL_PREFIX}{user_id}"
    count = await valkey_client.incr(key)
    # M1: EXPIRE ... NX — fija el TTL solo si la key no lo tiene. Preserva la
    # ventana fija (no la desliza) y auto-repara una key que quedó sin TTL.
    await valkey_client.expire(key, window_seconds, nx=True)
    if count > max_requests:
        raise HTTPException(status_code=429, detail="API rate limit exceeded")
