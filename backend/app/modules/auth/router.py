"""
Endpoints de autenticación JWT para FIM Platform (Change 04).

POST /auth/login   — emite access + refresh token
POST /auth/refresh — rota el refresh token
POST /auth/logout  — revoca ambos tokens en la blacklist Valkey
"""

import time
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from jose import JWTError
from sqlmodel import Session, select

from app.core.audit import write_audit_log
from app.core.config import settings
from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.rate_limit import check_login_rate_limit
from app.core.security import (
    BLACKLIST_PREFIX,
    REFRESH_TOKEN_EXPIRE_DAYS,
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.core.valkey import get_valkey_client
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AuthUserOut,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RefreshResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_REFRESH_MAX_AGE = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600

# Ventana de gracia para refreshes CONCURRENTES. La rotación single-use blacklistea
# el token viejo al usarlo; sin gracia, dos refreshes casi simultáneos con el mismo
# token (recarga de página que dispara varias requests, múltiples tabs, reconexión
# SSE) hacen que uno gane y el otro reciba "revoked" → deslogueo espurio. Durante la
# ventana, el refresh perdedor recibe la sesión ya rotada por el ganador.
_REFRESH_GRACE_PREFIX = "fim:refresh_grace:"
_REFRESH_GRACE_TTL_S = 10


def _set_refresh_cookie(response: Response, token: str) -> None:
    # secure=True exige HTTPS: el navegador descarta la cookie en HTTP. En dev
    # (HTTP local) se desactiva para que login/refresh funcionen; en prod (HTTPS)
    # queda activo.
    # Delete the legacy broad-path cookie before issuing the canonical cookie.
    # Both Set-Cookie headers are intentional: they prevent path shadowing during
    # the migration from Path=/ to Path=/auth/refresh.
    response.delete_cookie(key=_REFRESH_COOKIE, path="/")
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.environment != "dev",
        samesite="strict",
        path="/auth/refresh",
        max_age=_REFRESH_MAX_AGE,
    )


def clear_refresh_cookies(response: Response) -> None:
    """Expire canonical and legacy cookies so neither can shadow the other."""
    response.delete_cookie(key=_REFRESH_COOKIE, path="/auth/refresh")
    response.delete_cookie(key=_REFRESH_COOKIE, path="/")


def _to_auth_user_out(user: User) -> AuthUserOut:
    """Proyección del usuario autenticado para las respuestas de login/refresh (C38)."""
    return AuthUserOut(
        id=user.id,  # type: ignore[arg-type]
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    ip = request.client.host if request.client else "unknown"
    await check_login_rate_limit(body.username, ip)

    user = session.exec(select(User).where(User.username == body.username)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    jti_access = str(uuid4())
    jti_refresh = str(uuid4())
    access_token = create_access_token(
        user_id=user.id,  # type: ignore[arg-type]
        username=user.username,
        must_change_password=user.must_change_password,
        jti=jti_access,
        refresh_jti=jti_refresh,
    )
    refresh_token = create_refresh_token(user_id=user.id, jti=jti_refresh)  # type: ignore[arg-type]
    _set_refresh_cookie(response, refresh_token)

    write_audit_log(session, "login", user.id, extra=f"ip={ip}")  # type: ignore[arg-type]

    return LoginResponse(
        access_token=access_token,
        must_change_password=user.must_change_password,
        user=_to_auth_user_out(user),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    valkey_client=Depends(get_valkey_client),
    session: Session = Depends(get_session),
) -> RefreshResponse:
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    try:
        payload = decode_token(refresh_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    old_jti: str | None = payload.get("jti")
    if old_jti and valkey_client.exists(f"{BLACKLIST_PREFIX}{old_jti}"):
        # El token ya fue rotado. Si estamos dentro de la ventana de gracia es un
        # refresh concurrente (no reuso malicioso): devolvemos la sesión ya rotada
        # por el ganador en vez de 401. Pasada la ventana, es reuso real → 401.
        grace = valkey_client.get(f"{_REFRESH_GRACE_PREFIX}{old_jti}")
        if grace is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
            )
        winning_refresh = grace.decode() if isinstance(grace, (bytes, bytearray)) else grace
        try:
            winning_payload = decode_token(winning_refresh)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
            )
        winning_jti = winning_payload.get("jti")
        # Grace only reconciles concurrent uses of R0. It must never resurrect
        # its winner R1 after logout or password change has revoked R1.
        if not winning_jti or valkey_client.exists(f"{BLACKLIST_PREFIX}{winning_jti}"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
            )
        user = session.exec(select(User).where(User.id == int(payload["sub"]))).first()
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        access_token = create_access_token(
            user_id=user.id,  # type: ignore[arg-type]
            username=user.username,
            must_change_password=user.must_change_password,
            jti=str(uuid4()),
            refresh_jti=winning_jti,
        )
        # Devolver el MISMO refresh que emitió el ganador → ambos clientes quedan
        # con una sesión coherente.
        _set_refresh_cookie(response, winning_refresh)
        return RefreshResponse(access_token=access_token, user=_to_auth_user_out(user))

    if old_jti:
        blacklist_token(old_jti, payload["exp"], valkey_client)

    user_id = int(payload["sub"])
    user = session.exec(select(User).where(User.id == user_id)).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    jti_access = str(uuid4())
    jti_refresh = str(uuid4())
    access_token = create_access_token(
        user_id=user.id,  # type: ignore[arg-type]
        username=user.username,
        must_change_password=user.must_change_password,
        jti=jti_access,
        refresh_jti=jti_refresh,
    )
    new_refresh = create_refresh_token(user_id=user.id, jti=jti_refresh)  # type: ignore[arg-type]
    # Guardar el refresh "ganador" para que un refresh concurrente con el token
    # viejo (dentro de la ventana) reciba esta misma sesión en vez de 401.
    if old_jti:
        valkey_client.setex(f"{_REFRESH_GRACE_PREFIX}{old_jti}", _REFRESH_GRACE_TTL_S, new_refresh)
    _set_refresh_cookie(response, new_refresh)

    return RefreshResponse(access_token=access_token, user=_to_auth_user_out(user))


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
) -> LogoutResponse:
    payload = user.__dict__.get("_token_payload", {})
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        blacklist_token(jti, exp, valkey_client)

    refresh_jti = payload.get("refresh_jti")
    refresh_exp = None
    if refresh_token:
        try:
            rp = decode_token(refresh_token)
            refresh_jti = rp.get("jti") or refresh_jti
            refresh_exp = rp.get("exp")
        except JWTError:
            pass
    if refresh_jti:
        # Access and refresh tokens are minted together. The access token carries
        # the refresh JTI because the canonical cookie is intentionally scoped to
        # /auth/refresh and therefore cannot travel to /auth/logout.
        blacklist_token(refresh_jti, refresh_exp or time.time() + _REFRESH_MAX_AGE, valkey_client)

    clear_refresh_cookies(response)
    write_audit_log(session, "logout", user.id)  # type: ignore[arg-type]

    return LogoutResponse(message="logged_out")
