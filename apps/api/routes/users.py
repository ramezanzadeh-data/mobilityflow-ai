from fastapi import APIRouter, Depends, HTTPException, Security
from db.database import username_exists, create_user, get_user, update_user_password
from auth.password import hash_password, verify_password
from auth.permissions import can_manage_users
from apps.api.schemas.user import CurrentUser, UserCreate, ChangePasswordRequest
from apps.api.dependencies.auth import get_current_user
from apps.api.dependencies.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=CurrentUser, summary="Get the authenticated user's identity")
def get_me(
    current_user=Security(get_current_user),
    _=Depends(enforce_rate_limit),
):
    # Fetched fresh from the DB (not from the JWT) so that must_change_password
    # is always current, even if it changed after the token was issued.
    user = get_user(current_user["username"])

    must_change_password = bool(user.get("must_change_password")) if user else False
    mfa_enabled = bool(user.get("mfa_enabled")) if user else False

    return CurrentUser(
        username=current_user["username"],
        role=current_user["role"],
        company=current_user.get("company"),
        must_change_password=must_change_password,
        mfa_enabled=mfa_enabled,
    )


@router.post("", response_model=CurrentUser, status_code=201, summary="Create a new user (ADMIN only)")
def create_new_user(
    payload: UserCreate,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    if not can_manage_users(current_user):
        raise HTTPException(status_code=403, detail="Missing required permission: users:manage")

    if username_exists(payload.username):
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' already exists.")

    hashed = hash_password(payload.password)

    create_user(payload.username, hashed, payload.role, payload.company, must_change_password=True)

    return CurrentUser(username=payload.username, role=payload.role, company=payload.company, must_change_password=True)


@router.patch("/me/password", response_model=dict, summary="Change the authenticated user's own password")
def change_my_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):
    user = get_user(current_user["username"])

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(payload.current_password, user["password"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current password")

    update_user_password(current_user["username"], hash_password(payload.new_password))

    return {"detail": "Password updated successfully"}
