"""Inbound TanBan webhook handling: verify, store, acknowledge."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from models import InboundWebhookEvent
from utc_datetime import utc_now

logger = logging.getLogger("tanban-cursor.webhooks")


def _extract_ids(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    board = payload.get("board") or {}
    obj = payload.get("object") or {}
    board_id = board.get("public_id") if isinstance(board, dict) else None
    object_id = obj.get("public_id") if isinstance(obj, dict) else None
    return (
        str(board_id) if board_id else None,
        str(object_id) if object_id else None,
    )


def record_inbound_event(
    db: Session,
    *,
    delivery_id: str,
    event: str,
    payload: dict[str, Any],
) -> tuple[InboundWebhookEvent, bool]:
    """Persist a delivery. Returns (row, duplicate)."""
    existing = (
        db.query(InboundWebhookEvent).filter(InboundWebhookEvent.delivery_id == delivery_id).one_or_none()
    )
    if existing is not None:
        return existing, True

    board_public_id, object_public_id = _extract_ids(payload)
    row = InboundWebhookEvent(
        delivery_id=delivery_id,
        event=event,
        board_public_id=board_public_id,
        object_public_id=object_public_id,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        processed=False,
        received_at=utc_now(),
    )
    db.add(row)
    db.flush()
    logger.info("recorded webhook delivery_id=%s event=%s", delivery_id, event)
    return row, False


def mark_processed(db: Session, row: InboundWebhookEvent, *, error: str | None = None) -> None:
    """Mark delivery as handled. ``error`` stores skip/failure detail when set."""
    row.processed = True
    row.process_error = error[:500] if error else None
    row.processed_at = utc_now()
