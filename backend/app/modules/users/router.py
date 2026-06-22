"""
Endpoints de gestión de usuario para FIM Platform (Change 04 + C20).

POST /users/change-password — cambio de password forzado (primer login)
                              o cambio voluntario con validación de actual.
GET  /users                 — listado paginado de admins (require_admin, C20).
POST /users                 — crear admin adicional (require_admin, C20).
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from jose import JWTError
from sqlmodel import Session, func, select

from app.core.audit import write_audit_log
from app.core.database import get_session
from app.core.deps import get_current_user, require_admin
from app.core.security import blacklist_token, decode_token, hash_password, verify_password
from app.core.valkey import get_valkey_client
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
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
    scope = payload.get("scope")

    if scope != "password_change_only":
        if not body.current_password or not verify_password(
            body.current_password, user.password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect current password",
            )

    if len(body.new_password) < 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 12 characters",
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
    if refresh_token:
        try:
            rp = decode_token(refresh_token)
            if rjti := rp.get("jti"):
                blacklist_token(rjti, rp.get("exp", 0), valkey_client)
        except JWTError:
            pass
    response.delete_cookie(key=_REFRESH_COOKIE, path="/auth/refresh")

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
            UserItem(id=u.id, email=u.username, created_at=u.created_at)  # type: ignore[arg-type]
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

    return CreateUserResponse(id=new_user.id, email=new_user.username)  # type: ignore[arg-type]
