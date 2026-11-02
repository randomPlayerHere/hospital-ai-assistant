import uuid
from datetime import date

from pydantic import BaseModel, EmailStr, Field

Password = Field(min_length=12, max_length=128)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Password
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date
    phone: str | None = Field(default=None, max_length=32)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class TokenPair(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_ticket: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Password


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Password


class MFAVerifyLoginRequest(BaseModel):
    mfa_ticket: str
    code: str = Field(min_length=6, max_length=6)


class MFASetupResponse(BaseModel):
    secret: str
    otpauth_url: str


class MFAEnableRequest(BaseModel):
    secret: str
    code: str = Field(min_length=6, max_length=6)


class MFADisableRequest(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=6)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    mfa_enabled: bool = False


class AdminCreateUser(BaseModel):
    email: EmailStr
    password: str = Password
    full_name: str = Field(min_length=1, max_length=255)
    role: str = Field(pattern="^(admin|doctor|staff)$")
    department_id: int | None = None
    specialization: str | None = None
