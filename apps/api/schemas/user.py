from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    # Either mfa_required is true (and only mfa_token is set - call
    # /auth/mfa/verify-login next), or the full token pair is set.
    mfa_required: bool = False
    mfa_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in_minutes: int | None = None
    must_change_password: bool = False


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class SessionItem(BaseModel):
    id: int
    issued_at: str
    expires_at: str
    user_agent: str | None = None


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaCodeRequest(BaseModel):
    code: str


class MfaVerifyLoginRequest(BaseModel):
    mfa_token: str
    code: str


class CurrentUser(BaseModel):
    username: str
    role: str
    company: str | None = None
    must_change_password: bool = False
    mfa_enabled: bool = False


class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    company: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
