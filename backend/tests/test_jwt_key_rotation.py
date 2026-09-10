"""US-03: aceptación de JWT durante la rotación CURRENT/PREVIOUS."""

from datetime import datetime, timedelta, timezone

import pytest
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import decode_token


def _access_token(secret: str, subject: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "jti": f"jti-{subject}",
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )


def test_decode_token_acepta_clave_actual_y_anterior_durante_rotacion(monkeypatch) -> None:
    current = "test-current-rotation-key-32-chars"
    previous = "test-previous-rotation-key-32-char"
    monkeypatch.setattr(settings, "jwt_secret_current", current)
    monkeypatch.setattr(settings, "jwt_secret_previous", previous)

    assert decode_token(_access_token(current, "current"))["sub"] == "current"
    assert decode_token(_access_token(previous, "previous"))["sub"] == "previous"


def test_decode_token_no_acepta_una_clave_ajena_a_la_rotacion(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_current", "test-current-rotation-key-32-chars")
    monkeypatch.setattr(settings, "jwt_secret_previous", "test-previous-rotation-key-32-char")

    with pytest.raises(JWTError):
        decode_token(_access_token("test-untrusted-rotation-key-32-char", "unknown"))
