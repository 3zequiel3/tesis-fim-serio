from pydantic import BaseModel


class ChangePasswordRequest(BaseModel):
    current_password: str | None = None
    new_password: str


class ChangePasswordResponse(BaseModel):
    message: str
