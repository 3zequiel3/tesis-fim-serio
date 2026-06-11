"""
JWT dual-key y password hashing (Argon2id) para FIM Platform.

Decisiones de diseño:
- Dual-key (CURRENT + PREVIOUS) permite rotación de secreto sin invalidar
  sesiones activas. decode_token intenta CURRENT primero; si falla, PREVIOUS.
- jti (UUID v4) en cada token habilita revocación individual en blacklist.
- scope="password_change_only" en el access token bloquea endpoints normales
  cuando must_change_password=True (Change 04, D-E).
"""

import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings

_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
BLACKLIST_PREFIX = "fim:blacklist:"


def create_access_token(
    user_id: int,
    username: str,
    must_change_password: bool,
    jti: str,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": str(user_id),
        "username": username,
        "jti": jti,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if must_change_password:
        payload["scope"] = "password_change_only"
    return jwt.encode(payload, settings.jwt_secret_current, algorithm="HS256")


def create_refresh_token(user_id: int, jti: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.jwt_secret_current, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Decode JWT trying CURRENT key first, fallback to PREVIOUS."""
    try:
        return jwt.decode(token, settings.jwt_secret_current, algorithms=["HS256"])
    except JWTError:
        if not settings.jwt_secret_previous:
            raise
        return jwt.decode(token, settings.jwt_secret_previous, algorithms=["HS256"])


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def blacklist_token(jti: str, exp: int | float, valkey_client) -> None:
    """Add jti to Valkey blacklist with TTL = remaining seconds until expiry."""
    ttl = int(exp - time.time())
    if ttl > 0:
        valkey_client.setex(f"{BLACKLIST_PREFIX}{jti}", ttl, "1")
