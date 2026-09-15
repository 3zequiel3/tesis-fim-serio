"""
Endpoints de gestión de usuario para FIM Platform (Change 04 + C20).

POST /users/change-password — cambio de password forzado (primer login)
                              o cambio voluntario con validación de actual.
GET  /users                 — listado paginado de admins (require_admin, C20).
POST /users                 — crear admin adicional (require_admin, C20).
"""

import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from jose import JWTError
from sqlmodel import Session, func, select

from app.core.audit import write_audit_log
from app.core.database import get_session
from app.core.deps import get_current_user, require_admin
from app.core.security import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    blacklist_token,
    decode_token,
    hash_password,
    password_policy_error,
    verify_password,
)
from app.core.valkey import get_valkey_client
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.auth.router import clear_refresh_cookies
from app.modules.users.schemas import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    CreateUserRequest,
    CreateUserResponse,
    UserItem,
    UserListResponse,
)

router = APIRouter(prefix="/users", tags=["users"])

_REFRESH_COOKIE = "refresh_token"


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    valkey_client=Depends(get_valkey_client),
) -> ChangePasswordResponse:
    payload = user.__dict__.get("_token_payload", {})

    # Verified regardless of scope (D-2): the seed admin knows the password
    # used to obtain even a password_change_only token.
    if not body.current_password or not verify_password(
        body.current_password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect current password",
        )

    policy_error = password_policy_error(body.new_password)
    if policy_error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=policy_error,
        )

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    session.add(user)
    session.commit()

    # Revoke current access token
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        blacklist_token(jti, exp, valkey_client)

    # Revoke refresh token and clear cookie
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
        blacklist_token(
            refresh_jti,
            refresh_exp or time.time() + REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
            valkey_client,
        )
    clear_refresh_cookies(response)

    write_audit_log(session, "change_password", user.id)  # type: ignore[arg-type]

    return ChangePasswordResponse(message="password_changed")


# ── C20: admin user management ───────────────────────────────────────────────

@router.get("", response_model=UserListResponse)
async def list_users(
    offset: int = 0,
    limit: int = 50,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> UserListResponse:
    """Listado paginado de usuarios. No incluye password_hash. (RN-45)"""
    total = session.exec(select(func.count()).select_from(User)).one()
    users = session.exec(select(User).offset(offset).limit(limit)).all()
    return UserListResponse(
        items=[
            UserItem(id=u.id, email=u.email, created_at=u.created_at)  # type: ignore[arg-type]
            for u in users
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> CreateUserResponse:
    """Crea un admin adicional. Escribe audit_log con action='user_created'. (RN-45)"""
    import sqlalchemy.exc

    new_user = User(
        username=body.email,
        email=body.email,
        password_hash=hash_password(body.password),
        role="admin",
        is_active=True,
        must_change_password=True,
    )
    session.add(new_user)
    try:
        session.flush()
    except sqlalchemy.exc.IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email_already_exists",
        )

    session.refresh(new_user)

    audit = AuditLog(
        user_id=admin.id,  # type: ignore[arg-type]
        action="user_created",
        target_type="user",
        target_id=new_user.id,
    )
    session.add(audit)
    session.commit()

    return CreateUserResponse(id=new_user.id, email=new_user.email)  # type: ignore[arg-type]
