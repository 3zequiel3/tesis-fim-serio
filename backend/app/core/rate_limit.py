"""
Helpers de rate limiting con sliding-window en Valkey (D7).

Login: 5 intentos / 15 min por (username + IP).
API autenticada: 100 req/min por user_id.

El incremento ocurre ANTES de la verificación para contar también los
intentos rechazados y evitar timing oracle.
"""

from fastapi import HTTPException

LOGIN_RL_PREFIX = "fim:rl:login:"
API_RL_PREFIX = "fim:rl:api:"
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 900
API_MAX_REQUESTS = 100
API_WINDOW_SECONDS = 60


def check_login_rate_limit(username: str, ip: str, valkey_client) -> None:
    key = f"{LOGIN_RL_PREFIX}{username}:{ip}"
    count = valkey_client.incr(key)
    if count == 1:
        valkey_client.expire(key, LOGIN_WINDOW_SECONDS)
    if count > LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(LOGIN_WINDOW_SECONDS)},
        )


def check_api_rate_limit(user_id: int, valkey_client) -> None:
    key = f"{API_RL_PREFIX}{user_id}"
    count = valkey_client.incr(key)
    if count == 1:
        valkey_client.expire(key, API_WINDOW_SECONDS)
    if count > API_MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="API rate limit exceeded")
