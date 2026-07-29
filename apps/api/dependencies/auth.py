import os

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt import TokenError, verify_access_token
from db.database import (
    clear_current_tenant,
    role_has_permission,
    set_current_tenant,
)

# -------------------------------
# Security
# -------------------------------

security = HTTPBearer(
    scheme_name="BearerAuth"
)

_LEGACY_API_KEY = os.environ.get("API_KEY")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
):
    """
    Authenticate the current request.

    Priority:
    1. Bearer JWT
    2. Legacy API Key (optional)
    3. Otherwise -> 401 Unauthorized
    """

    # -------------------------------
    # Bearer JWT
    # -------------------------------

    if credentials:

        if credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Authorization scheme must be Bearer.",
            )

        try:

            payload = verify_access_token(
                credentials.credentials
            )

            tenant_id = payload.get("tenant_id")

            set_current_tenant(tenant_id)

            return {
                "username": payload["sub"],
                "role": payload["role"],
                "company": payload.get("company"),
                "tenant_id": tenant_id,
            }

        except TokenError as exc:

            clear_current_tenant()

            raise HTTPException(
                status_code=401,
                detail=str(exc),
            )


    # -------------------------------
    # Legacy API Key
    # -------------------------------

    if _LEGACY_API_KEY:

        raise HTTPException(
            status_code=401,
            detail="Use Bearer JWT authentication.",
        )


    # -------------------------------
    # Missing authentication
    # -------------------------------

    clear_current_tenant()

    raise HTTPException(
        status_code=401,
        detail="Authorization header is required.",
    )



def require_company(current_user):

    company = current_user.get("company")

    if not company:
        raise HTTPException(
            status_code=400,
            detail="Authenticated user has no company.",
        )

    return company



def require_tenant_id(current_user):

    tenant_id = current_user.get("tenant_id")

    if tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Authenticated user has no tenant.",
        )

    return tenant_id



def require_permission(permission_name):

    def checker(
        current_user=Security(get_current_user)
    ):

        if not role_has_permission(
            current_user["role"],
            permission_name,
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Missing required permission: {permission_name}",
            )

        return current_user

    return checker