from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthUserOut(BaseModel):
    """Usuario autenticado embebido en las respuestas de login/refresh (C38).

    Cierra el FIX-01 de C38: el frontend tipaba `user` en LoginResponse/
    RefreshResponse pero el backend nunca lo enviaba, por lo que el navbar
    no mostraba el usuario logueado.
    """

    id: int
    username: str
    role: str
    must_change_password: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool
    user: AuthUserOut


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserOut


class LogoutResponse(BaseModel):
    message: str
