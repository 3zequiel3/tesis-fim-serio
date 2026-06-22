from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


class ChangePasswordRequest(BaseModel):
    current_password: str | None = None
    new_password: str


class ChangePasswordResponse(BaseModel):
    message: str


# ── C20: user management ────────────────────────────────────────────────────

class UserItem(BaseModel):
    id: int
    email: str
    created_at: datetime


class UserListResponse(BaseModel):
    items: list[UserItem]
    total: int
    offset: int
    limit: int


class CreateUserRequest(BaseModel):
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("password must be at least 12 characters")
        return v


class CreateUserResponse(BaseModel):
    id: int
    email: str
