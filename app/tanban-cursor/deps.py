from fastapi import Header, HTTPException, Request

from config import settings
from services import webhook_verify


async def require_tanban_webhook_signature(
    request: Request,
    x_tanban_signature: str | None = Header(default=None, alias="X-TanBan-Signature"),
    x_tanban_delivery: str | None = Header(default=None, alias="X-TanBan-Delivery"),
    x_tanban_event: str | None = Header(default=None, alias="X-TanBan-Event"),
) -> tuple[bytes, str | None, str | None]:
    body = await request.body()
    secret = settings.tanban_webhook_secret
    if secret:
        if not x_tanban_signature:
            raise HTTPException(status_code=401, detail="Missing X-TanBan-Signature")
        if not webhook_verify.verify_signature(secret, body, x_tanban_signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif settings.is_production:
        raise HTTPException(status_code=500, detail="TANBAN_WEBHOOK_SECRET must be set in production")
    return body, x_tanban_delivery, x_tanban_event
