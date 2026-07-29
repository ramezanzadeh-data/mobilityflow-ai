from fastapi import APIRouter, Depends, HTTPException, Request

from auth.service import authenticate_user
from auth.jwt import (
    create_access_token,
    create_mfa_pending_token,
    verify_mfa_pending_token,
    TokenError,
    JWT_EXPIRY_MINUTES,
)
from auth.mfa import generate_mfa_secret, get_provisioning_uri, verify_totp_code
from auth.refresh import (
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry_timestamp,
)
from db.database import (
    get_user,
    set_mfa_secret,
    set_mfa_enabled,
    create_refresh_token,
    get_refresh_token,
    revoke_refresh_token,
    revoke_session,
    revoke_all_sessions_for_user,
    list_active_sessions,
    log_security_event,
)
from apps.api.schemas.user import (
    LoginRequest,
    LoginResponse,
    TokenPairResponse,
    RefreshRequest,
    LogoutRequest,
    SessionItem,
    MfaSetupResponse,
    MfaCodeRequest,
    MfaVerifyLoginRequest,
)
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token_pair(user, request: Request):

    access_token = create_access_token(
        username=user["username"],
        role=user["role"],
        company=user["company"],
        tenant_id=user.get("tenant_id"),
    )

    refresh_token = generate_refresh_token()
    user_agent = request.headers.get("user-agent") if request else None

    create_refresh_token(
        username=user["username"],
        token_hash=hash_refresh_token(refresh_token),
        tenant_id=user.get("tenant_id"),
        expires_at=refresh_token_expiry_timestamp(),
        user_agent=user_agent,
    )

    return access_token, refresh_token


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Log in and obtain a JWT access token + refresh token",
    description="Authenticates with the same credentials used for the Streamlit app. "
                 "If the account has MFA enabled, this returns mfa_required=true with a "
                 "short-lived mfa_token instead of real tokens - call /auth/mfa/verify-login next. "
                 "Successful and failed attempts are recorded in the security audit log.",
)
def login(credentials: LoginRequest, request: Request, _=Depends(enforce_rate_limit)):

    user = authenticate_user(credentials.username, credentials.password)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user.get("mfa_enabled"):
        mfa_token = create_mfa_pending_token(user["username"])
        return LoginResponse(mfa_required=True, mfa_token=mfa_token)

    access_token, refresh_token = _issue_token_pair(user, request)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_minutes=JWT_EXPIRY_MINUTES,
        must_change_password=bool(user.get("must_change_password")),
    )


@router.post(
    "/mfa/verify-login",
    response_model=LoginResponse,
    summary="Complete login for an MFA-enabled account",
)
def mfa_verify_login(payload: MfaVerifyLoginRequest, request: Request, _=Depends(enforce_rate_limit)):

    try:
        pending = verify_mfa_pending_token(payload.mfa_token)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))

    username = pending["sub"]
    user = get_user(username)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid MFA session")

    if not verify_totp_code(user.get("mfa_secret"), payload.code):
        log_security_event(username, "MFA_LOGIN", "Invalid MFA code", success=False)
        raise HTTPException(status_code=401, detail="Invalid MFA code")

    log_security_event(username, "MFA_LOGIN", "MFA code verified", success=True)

    access_token, refresh_token = _issue_token_pair(user, request)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_minutes=JWT_EXPIRY_MINUTES,
        must_change_password=bool(user.get("must_change_password")),
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="Exchange a refresh token for a new access token (rotates the refresh token)",
)
def refresh_token_endpoint(payload: RefreshRequest, request: Request, _=Depends(enforce_rate_limit)):

    token_hash = hash_refresh_token(payload.refresh_token)
    session = get_refresh_token(token_hash)

    from auth.refresh import now_timestamp

    if not session or session["revoked"] or session["expires_at"] < now_timestamp():
        raise HTTPException(status_code=401, detail="Refresh token is invalid, expired, or revoked")

    user = get_user(session["username"])

    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")

    # Rotate: the old refresh token is single-use - revoking it here means
    # a stolen-and-replayed refresh token stops working the moment the
    # legitimate client uses it once.
    revoke_refresh_token(token_hash)

    access_token, new_refresh_token = _issue_token_pair(user, request)

    return TokenPairResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in_minutes=JWT_EXPIRY_MINUTES,
    )


@router.post("/logout", summary="Revoke a single refresh token (log out this device/session)")
def logout(payload: LogoutRequest, _=Depends(enforce_rate_limit)):

    revoke_refresh_token(hash_refresh_token(payload.refresh_token))

    return {"detail": "Logged out"}


@router.post("/logout-all", summary="Revoke every active session for the current user")
def logout_all(current_user=Depends(get_current_user), _=Depends(enforce_rate_limit)):

    revoke_all_sessions_for_user(current_user["username"])

    return {"detail": "All sessions revoked"}


@router.get("/sessions", response_model=list[SessionItem], summary="List active sessions for the current user")
def get_sessions(current_user=Depends(get_current_user), _=Depends(enforce_rate_limit)):

    return list_active_sessions(current_user["username"])


@router.delete("/sessions/{session_id}", summary="Revoke one specific session by id")
def delete_session(
    session_id: int,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    revoked = revoke_session(session_id, current_user["username"])

    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"detail": "Session revoked"}


@router.post(
    "/mfa/setup",
    response_model=MfaSetupResponse,
    summary="Start MFA setup - returns a TOTP secret + provisioning URI for an authenticator app",
)
def mfa_setup(current_user=Depends(get_current_user), _=Depends(enforce_rate_limit)):

    secret = generate_mfa_secret()
    set_mfa_secret(current_user["username"], secret)

    return MfaSetupResponse(
        secret=secret,
        provisioning_uri=get_provisioning_uri(secret, current_user["username"]),
    )


@router.post("/mfa/enable", summary="Confirm MFA setup with a code from the authenticator app")
def mfa_enable(payload: MfaCodeRequest, current_user=Depends(get_current_user), _=Depends(enforce_rate_limit)):

    user = get_user(current_user["username"])

    if not user or not user.get("mfa_secret"):
        raise HTTPException(status_code=400, detail="Call /auth/mfa/setup first")

    if not verify_totp_code(user["mfa_secret"], payload.code):
        raise HTTPException(status_code=401, detail="Invalid code")

    set_mfa_enabled(current_user["username"], True)

    return {"detail": "MFA enabled"}


@router.post("/mfa/disable", summary="Disable MFA (requires a valid current code)")
def mfa_disable(payload: MfaCodeRequest, current_user=Depends(get_current_user), _=Depends(enforce_rate_limit)):

    user = get_user(current_user["username"])

    if not user or not user.get("mfa_enabled"):
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    if not verify_totp_code(user["mfa_secret"], payload.code):
        raise HTTPException(status_code=401, detail="Invalid code")

    set_mfa_enabled(current_user["username"], False)
    set_mfa_secret(current_user["username"], None)

    return {"detail": "MFA disabled"}
