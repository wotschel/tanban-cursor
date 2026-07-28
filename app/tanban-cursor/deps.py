import hmac
import json

from fastapi import Header, HTTPException, Query, Request

from config import settings
from services import webhook_verify
from services.tanban_boards import board_public_id_from_body


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not value.strip():
        return None
    return value.strip()


def require_status_ui_token(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    x_status_ui_token: str | None = Header(default=None, alias="X-Status-UI-Token"),
) -> str:
    """Require the operator status-UI token (query, Bearer, or header)."""
    provided = (token or "").strip() or _extract_bearer(authorization) or (x_status_ui_token or "").strip()
    expected = settings.status_ui_access_token()
    if not provided or len(provided) != len(expected) or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing status UI token")
    return provided


async def require_tanban_webhook_signature(
    request: Request,
    x_tanban_signature: str | None = Header(default=None, alias="X-TanBan-Signature"),
    x_tanban_delivery: str | None = Header(default=None, alias="X-TanBan-Delivery"),
    x_tanban_event: str | None = Header(default=None, alias="X-TanBan-Event"),
) -> tuple[bytes, str | None, str | None]:
    body = await request.body()
    secrets = settings.webhook_secrets()

    if secrets:
        if not x_tanban_signature:
            raise HTTPException(status_code=401, detail="Missing X-TanBan-Signature")

        board_public_id = board_public_id_from_body(body)
        binding = settings.resolve_board(board_public_id)
        if binding is not None and getattr(binding, "webhook_secret", ""):
            candidate_secrets = [binding.webhook_secret]
        elif settings.tanban_boards:
            # Known multi-board config but unknown/missing board → reject.
            raise HTTPException(status_code=401, detail="Unknown or missing board for webhook signature")
        else:
            # Legacy single-secret mode: accept any board signed with that secret.
            candidate_secrets = secrets

        if not any(webhook_verify.verify_signature(secret, body, x_tanban_signature) for secret in candidate_secrets):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif settings.is_production:
        raise HTTPException(
            status_code=500,
            detail="TANBAN_BOARDS (or TANBAN_WEBHOOK_SECRET) must be set in production",
        )

    # Reject non-object JSON early when signature checks passed or were skipped.
    if body:
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from error
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    return body, x_tanban_delivery, x_tanban_event
