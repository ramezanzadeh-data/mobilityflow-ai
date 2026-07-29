from pydantic import BaseModel, field_validator

from core.security.url_safety import UnsafeUrlError, validate_public_https_url


class WebhookCreateRequest(BaseModel):
    url: str
    event_type: str = "ALL"

    @field_validator("url")
    @classmethod
    def _validate_url_is_safe(cls, value: str) -> str:
        try:
            validate_public_https_url(value)
        except UnsafeUrlError as exc:
            raise ValueError(str(exc)) from exc

        return value


class WebhookResponse(BaseModel):
    id: int
    url: str
    event_type: str
    is_active: bool
    created_at: str
    secret: str | None = None
