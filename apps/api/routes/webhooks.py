import secrets as secrets_module

from fastapi import APIRouter, Depends, HTTPException

from db.database import create_webhook, get_webhooks_for_company, delete_webhook
from apps.api.schemas.webhook import WebhookCreateRequest, WebhookResponse
from apps.api.dependencies.auth import get_current_user, require_company, require_permission
from apps.api.dependencies.rate_limit import enforce_rate_limit

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "",
    response_model=WebhookResponse,
    status_code=201,
    summary="Register a new webhook",
    description="The returned 'secret' is shown ONLY ONCE, at creation time - "
                 "store it securely, it cannot be retrieved again. Use it to "
                 "verify the 'X-Webhook-Signature' header on incoming deliveries.",
)
def register_webhook(
    webhook_request: WebhookCreateRequest,
    current_user=Depends(require_permission("webhooks:manage")),
    _=Depends(enforce_rate_limit),
):

    company = require_company(current_user)

    secret = secrets_module.token_hex(24)

    webhook_id = create_webhook(
        company, webhook_request.url, webhook_request.event_type, secret
    )

    created = next(
        w for w in get_webhooks_for_company(company) if w[0] == webhook_id
    )

    return WebhookResponse(
        id=created[0],
        url=created[2],
        event_type=created[3],
        is_active=bool(created[5]),
        created_at=created[6],
        secret=secret,
    )


@router.get(
    "",
    response_model=list[WebhookResponse],
    summary="List your company's webhooks",
    description="The 'secret' field is never returned here (only once, at creation).",
)
def list_webhooks(
    current_user=Depends(get_current_user),
    _=Depends(enforce_rate_limit),
):

    company = require_company(current_user)

    webhooks = get_webhooks_for_company(company)

    return [
        WebhookResponse(
            id=w[0], url=w[2], event_type=w[3], is_active=bool(w[5]),
            created_at=w[6], secret=None
        )
        for w in webhooks
    ]


@router.delete("/{webhook_id}", status_code=204, summary="Delete a webhook")
def remove_webhook(
    webhook_id: int,
    current_user=Depends(require_permission("webhooks:manage")),
    _=Depends(enforce_rate_limit),
):

    company = require_company(current_user)

    owned_ids = {w[0] for w in get_webhooks_for_company(company)}

    if webhook_id not in owned_ids:
        raise HTTPException(status_code=404, detail="Webhook not found for this company")

    delete_webhook(webhook_id)

    return None
