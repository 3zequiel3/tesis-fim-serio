"""
Endpoints de autenticación JWT para FIM Platform (Change 04).

POST /auth/login   — emite access + refresh token
POST /auth/refresh — rota el refresh token
POST /auth/logout  — revoca ambos tokens en la blacklist Valkey
"""

from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from jose import JWTError
from sqlmodel import Session, select

from app.core.audit import write_audit_log
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
from app.modules.auth.schemas import LoginRequest, LoginResponse, LogoutResponse, RefreshResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_REFRESH_MAX_AGE = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/auth/refresh",
        max_age=_REFRESH_MAX_AGE,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path="/auth/refresh")


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
    )
    refresh_token = create_refresh_token(user_id=user.id, jti=jti_refresh)  # type: ignore[arg-type]
    _set_refresh_cookie(response, refresh_token)

    write_audit_log(session, "login", user.id, extra=f"ip={ip}")  # type: ignore[arg-type]

    return LoginResponse(
        access_token=access_token,
        must_change_password=user.must_change_password,
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

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
    )
    new_refresh = create_refresh_token(user_id=user.id, jti=jti_refresh)  # type: ignore[arg-type]
    _set_refresh_cookie(response, new_refresh)

    return RefreshResponse(access_token=access_token)


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

    if refresh_token:
        try:
            rp = decode_token(refresh_token)
            if rjti := rp.get("jti"):
                blacklist_token(rjti, rp.get("exp", 0), valkey_client)
        except JWTError:
            pass

    _clear_refresh_cookie(response)
    write_audit_log(session, "logout", user.id)  # type: ignore[arg-type]

    return LogoutResponse(message="logged_out")
