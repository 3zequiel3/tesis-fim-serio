"""
Helpers de rate limiting con sliding-window en Valkey (D7, C20).

Login: configurable via RATE_LIMIT_LOGIN_ATTEMPTS / RATE_LIMIT_LOGIN_WINDOW_SECONDS.
API autenticada: configurable via RATE_LIMIT_API_PER_MINUTE.

Defaults: 5 intentos / 15 min (login), 100 req/min (API) — idénticos a las
constantes hardcodeadas anteriores (no breaking change).

El incremento ocurre ANTES de la verificación para contar también los
intentos rechazados y evitar timing oracle.

Las funciones usan el cliente Valkey async (get_async_valkey_client) para no
bloquear el event loop. El parámetro valkey_client es opcional para permitir
inyección en tests; si no se provee, se usa el singleton async.
"""

from fastapi import HTTPException

from app.core.config import settings

LOGIN_RL_PREFIX = "fim:rl:login:"
API_RL_PREFIX = "fim:rl:api:"


async def check_login_rate_limit(username: str, ip: str, valkey_client=None) -> None:
    if valkey_client is None:
        from app.core.valkey import get_async_valkey_client
        valkey_client = get_async_valkey_client()
    max_attempts = settings.rate_limit_login_attempts
    window_seconds = settings.rate_limit_login_window_seconds
    key = f"{LOGIN_RL_PREFIX}{username}:{ip}"
    count = await valkey_client.incr(key)
    if count == 1:
        await valkey_client.expire(key, window_seconds)
    if count > max_attempts:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(window_seconds)},
        )


async def check_api_rate_limit(user_id: int, valkey_client=None) -> None:
    if valkey_client is None:
        from app.core.valkey import get_async_valkey_client
        valkey_client = get_async_valkey_client()
    max_requests = settings.rate_limit_api_per_minute
    window_seconds = 60
    key = f"{API_RL_PREFIX}{user_id}"
    count = await valkey_client.incr(key)
    if count == 1:
        await valkey_client.expire(key, window_seconds)
    if count > max_requests:
        raise HTTPException(status_code=429, detail="API rate limit exceeded")
