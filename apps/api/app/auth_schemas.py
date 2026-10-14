"""Request and response contracts for application authentication."""

import re

from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class SignupRequest(BaseModel):
    """회원가입. 회사 없이 무료 요금제 일반 사용자로 만들고, 첫 로그인 뒤 회사 프로필을 직접 만든다."""

    username: str = Field(min_length=4, max_length=30)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{3,29}", normalized):
            raise ValueError("아이디는 영문 소문자·숫자·. _ - 로 4~30자이고, 영문이나 숫자로 시작해야 합니다.")
        return normalized

    @model_validator(mode="after")
    def password_is_not_trivial(self) -> "SignupRequest":
        if self.password.strip().casefold() == self.username:
            raise ValueError("비밀번호는 아이디와 달라야 합니다.")
        if len(set(self.password)) < 4:
            raise ValueError("비밀번호에 서로 다른 글자를 4개 이상 넣어 주세요.")
        return self


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUserRead
