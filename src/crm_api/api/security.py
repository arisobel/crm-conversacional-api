import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import Header, HTTPException, Request, status

from crm_api.core.config import Settings


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid internal request",
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _unauthorized() from error
    if parsed.tzinfo is None:
        raise _unauthorized()
    return parsed.astimezone(UTC)


async def verify_internal_request(
    request: Request,
    x_tenant_slug: str | None = Header(default=None, alias="X-Tenant-Slug"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
    x_signature: str | None = Header(default=None, alias="X-Signature"),
) -> str:
    settings: Settings = request.app.state.settings
    if not x_tenant_slug or not x_timestamp or not x_signature:
        raise _unauthorized()
    if not hmac.compare_digest(x_tenant_slug, settings.tenant_slug):
        raise _unauthorized()

    timestamp = _parse_timestamp(x_timestamp)
    elapsed_seconds = abs((datetime.now(UTC) - timestamp).total_seconds())
    if elapsed_seconds > settings.internal_hmac_tolerance_seconds:
        raise _unauthorized()

    body = await request.body()
    canonical = b".".join(
        [
            x_timestamp.encode("utf-8"),
            request.method.encode("ascii"),
            request.url.path.encode("utf-8"),
            body,
        ]
    )
    expected = hmac.new(
        settings.internal_hmac_secret.get_secret_value().encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(x_signature, expected):
        raise _unauthorized()
    return x_tenant_slug
