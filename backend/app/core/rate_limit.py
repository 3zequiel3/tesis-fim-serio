"""
Helpers de rate limiting con sliding-window en Valkey (D7, C20).

Login: configurable via RATE_LIMIT_LOGIN_ATTEMPTS / RATE_LIMIT_LOGIN_WINDOW_SECONDS.
API autenticada: configurable via RATE_LIMIT_API_PER_MINUTE.

Defaults: 5 intentos / 15 min (login), 100 req/min (API) — idénticos a las
constantes hardcodeadas anteriores (no breaking change).

El incremento ocurre ANTES de la verificación para contar también los
intentos rechazados y evitar timing oracle.
"""

from fastapi import HTTPException

from app.core.config import settings

LOGIN_RL_PREFIX = "fim:rl:login:"
API_RL_PREFIX = "fim:rl:api:"


def check_login_rate_limit(username: str, ip: str, valkey_client) -> None:
    max_attempts = settings.rate_limit_login_attempts
    window_seconds = settings.rate_limit_login_window_seconds
    key = f"{LOGIN_RL_PREFIX}{username}:{ip}"
    count = valkey_client.incr(key)
    if count == 1:
        valkey_client.expire(key, window_seconds)
    if count > max_attempts:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(window_seconds)},
        )


def check_api_rate_limit(user_id: int, valkey_client) -> None:
    max_requests = settings.rate_limit_api_per_minute
    window_seconds = 60
    key = f"{API_RL_PREFIX}{user_id}"
    count = valkey_client.incr(key)
    if count == 1:
        valkey_client.expire(key, window_seconds)
    if count > max_requests:
        raise HTTPException(status_code=429, detail="API rate limit exceeded")
