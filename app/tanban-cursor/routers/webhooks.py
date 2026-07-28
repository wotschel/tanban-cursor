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


def _log_inbound_event(*, event: str, delivery_id: str, payload: dict, duplicate: bool) -> None:
    board = payload.get("board") if isinstance(payload.get("board"), dict) else {}
    obj = payload.get("object") if isinstance(payload.get("object"), dict) else {}
    labels = payload.get("labels") if isinstance(payload.get("labels"), dict) else {}
    logger.info(
        "tanban webhook event=%s delivery_id=%s duplicate=%s board=%s object_type=%s object=%s "
        "object_label=%r labels_added=%s labels_removed=%s",
        event,
        delivery_id,
        duplicate,
        board.get("public_id") or board.get("name") or "-",
        obj.get("type") or "-",
        obj.get("public_id") or "-",
        obj.get("label") or obj.get("title") or "",
        labels.get("added") or [],
        labels.get("removed") or [],
    )
    logger.info(
        "tanban webhook payload delivery_id=%s %s",
        delivery_id,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


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
    _log_inbound_event(event=event, delivery_id=delivery_id, payload=payload, duplicate=duplicate)
    if not duplicate:
        background_tasks.add_task(_process_delivery_background, delivery_id)
    return schemas.TanbanWebhookAck(
        status="ok",
        delivery_id=row.delivery_id,
        duplicate=duplicate,
    )
