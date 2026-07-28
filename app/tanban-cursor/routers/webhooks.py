import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas
from database import SessionLocal, get_db
from deps import require_tanban_webhook_signature
from services import dispatch, inbound_webhooks

logger = logging.getLogger("tanban-cursor.routers.webhooks")

router = APIRouter(tags=["webhooks"])


def _process_delivery_background(delivery_id: str) -> None:
    db = SessionLocal()
    try:
        dispatch.process_inbound_delivery(db, delivery_id)
    except Exception:  # noqa: BLE001 — never kill the worker on background failures
        logger.exception("background dispatch failed delivery_id=%s", delivery_id)
    finally:
        db.close()


@router.post("/webhooks/tanban", response_model=schemas.TanbanWebhookAck)
def receive_tanban_webhook(
    background_tasks: BackgroundTasks,
    verified: tuple[bytes, str | None, str | None] = Depends(require_tanban_webhook_signature),
    db: Session = Depends(get_db),
):
    body, delivery_header, event_header = verified
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    delivery_id = delivery_header or str(payload.get("id") or "").strip()
    event = event_header or str(payload.get("event") or "").strip()
    if not delivery_id:
        raise HTTPException(status_code=400, detail="Missing delivery id")
    if not event:
        raise HTTPException(status_code=400, detail="Missing event name")

    row, duplicate = inbound_webhooks.record_inbound_event(
        db,
        delivery_id=delivery_id,
        event=event,
        payload=payload,
    )
    db.commit()
    if not duplicate:
        logger.info("accepted webhook event=%s delivery_id=%s", event, delivery_id)
        background_tasks.add_task(_process_delivery_background, delivery_id)
    return schemas.TanbanWebhookAck(
        status="ok",
        delivery_id=row.delivery_id,
        duplicate=duplicate,
    )
