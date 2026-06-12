"""
Dependencies FastAPI para autenticación y control de acceso (Change 04).

get_current_user: valida JWT, verifica blacklist, aplica rate limit API.
require_full_access: bloquea tokens con scope=password_change_only.

El payload del JWT se adjunta al objeto User vía __dict__ para que
require_full_access y change-password puedan leer el scope y jti
sin re-decodificar el token.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.rate_limit import check_api_rate_limit
from app.core.security import BLACKLIST_PREFIX, decode_token
from app.core.valkey import get_valkey_client
from app.modules.auth.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
) -> User:
    try:
        payload = decode_token(token)
    except JWTError:
        raise _credentials_exc

    jti: str | None = payload.get("jti")
    if jti and valkey_client.exists(f"{BLACKLIST_PREFIX}{jti}"):
        raise _credentials_exc

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise _credentials_exc

    check_api_rate_limit(int(user_id), valkey_client)

    user = session.exec(select(User).where(User.id == int(user_id))).first()
    if user is None or not user.is_active:
        raise _credentials_exc

    user.__dict__["_token_payload"] = payload
    return user


async def require_full_access(user: User = Depends(get_current_user)) -> User:
    payload = user.__dict__.get("_token_payload", {})
    if payload.get("scope") == "password_change_only":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password_change_required",
        )
    return user


async def require_admin(user: User = Depends(require_full_access)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin_required",
        )
    return user
