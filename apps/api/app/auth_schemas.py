"""Request and response contracts for application authentication."""

from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class AuthUserRead(BaseModel):
    id: UUID
    username: str
    role: str
    company_id: UUID | None
    company_name: str | None


class AuthUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=256)
    # 비워 두면 회사가 없는 계정이다. 그 계정이 처음 로그인해 회사 프로필을 직접 만든다(시스템 관리자만 비울 수 있다).
    company_id: UUID | None = None
    role: Literal["ADMIN", "USER"] = "USER"

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUserRead
