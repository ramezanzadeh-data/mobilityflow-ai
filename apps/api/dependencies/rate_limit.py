
from fastapi import HTTPException, Request

from apps.api.middleware.rate_limiter import RateLimiter

_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)


def enforce_rate_limit(request: Request):

    client_key = request.client.host if request.client else "unknown"

    allowed, retry_after = _rate_limiter.is_allowed(client_key)

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after:.1f} seconds.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
