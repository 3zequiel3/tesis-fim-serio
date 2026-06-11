"""
Endpoints de gestión de usuario para FIM Platform (Change 04).

POST /users/change-password — cambio de password forzado (primer login)
                              o cambio voluntario con validación de actual.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from jose import JWTError
from sqlmodel import Session

from app.core.audit import write_audit_log
from app.core.database import get_session
from app.core.deps import get_current_user
from app.core.security import blacklist_token, decode_token, hash_password, verify_password
from app.core.valkey import get_valkey_client
from app.modules.auth.models import User
from app.modules.users.schemas import ChangePasswordRequest, ChangePasswordResponse

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
