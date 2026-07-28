"""Dispatch TanBan webhook events to Cursor cloud when labels match."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from config import settings
from models import CursorAgentRun, InboundWebhookEvent
from services import inbound_webhooks
from services.cursor_client import CursorClient, CursorClientError
from services.label_rules import (
    DISPATCH_EVENTS,
    LabelDecision,
    build_prompt,
    evaluate_labels,
    normalize_label_names,
)
from services.tanban_client import TanbanClient, TanbanClientError
from utc_datetime import utc_now

logger = logging.getLogger("tanban-cursor.dispatch")

ACTIVE_RUN_STATUSES = frozenset({"pending", "running", "creating"})


def _payload_dict(row: InboundWebhookEvent) -> dict[str, Any]:
    try:
        data = json.loads(row.payload_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _object_is_card(payload: dict[str, Any]) -> bool:
    obj = payload.get("object") or {}
    return isinstance(obj, dict) and str(obj.get("type") or "").casefold() == "card"


def _added_labels(payload: dict[str, Any]) -> set[str]:
    labels = payload.get("labels") or {}
    if not isinstance(labels, dict):
        return set()
    return normalize_label_names(labels.get("added"))


def _resolve_card(
    client: TanbanClient,
    *,
    card_public_id: str,
    payload: dict[str, Any],
    event: str,
) -> tuple[dict[str, Any] | None, set[str], str | None]:
    """Return (card_or_none, current_label_names, error)."""
    if settings.tanban_board_id is not None:
        try:
            card = client.find_card_by_public_id(settings.tanban_board_id, card_public_id)
        except TanbanClientError as error:
            return None, set(), str(error)
        if card is None:
            return None, set(), f"card public_id={card_public_id} not found on board {settings.tanban_board_id}"
        names = normalize_label_names(
            [str(label.get("name") or "") for label in (card.get("labels") or []) if isinstance(label, dict)]
        )
        return card, names, None

    # Fallback without board id: only card_created carries the full initial set in labels.added.
    if event == "card_created":
        return None, _added_labels(payload), None
    return None, set(), "TANBAN_BOARD_ID is required to resolve labels for this event"


def _has_active_run(db: Session, *, card_public_id: str, mode: str) -> bool:
    existing = (
        db.query(CursorAgentRun)
        .filter(
            CursorAgentRun.card_public_id == card_public_id,
            CursorAgentRun.mode == mode,
            CursorAgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .first()
    )
    return existing is not None


def process_inbound_delivery(db: Session, delivery_id: str) -> LabelDecision | None:
    """Evaluate and optionally launch Cursor for a stored inbound delivery."""
    row = db.query(InboundWebhookEvent).filter(InboundWebhookEvent.delivery_id == delivery_id).one_or_none()
    if row is None:
        logger.warning("delivery_id=%s not found", delivery_id)
        return None
    if row.processed:
        logger.info("delivery_id=%s already processed, skip", delivery_id)
        return None

    payload = _payload_dict(row)
    event = row.event

    if event not in DISPATCH_EVENTS:
        inbound_webhooks.mark_processed(db, row)
        db.commit()
        return LabelDecision(False, reason=f"event {event} ignored")

    if not _object_is_card(payload):
        inbound_webhooks.mark_processed(db, row)
        db.commit()
        return LabelDecision(False, reason="object is not a card")

    card_public_id = row.object_public_id
    if not card_public_id:
        inbound_webhooks.mark_processed(db, row, error="missing card public_id")
        db.commit()
        return LabelDecision(False, reason="missing card public_id")

    client = TanbanClient()
    card, current_labels, resolve_error = _resolve_card(
        client,
        card_public_id=card_public_id,
        payload=payload,
        event=event,
    )
    if resolve_error:
        inbound_webhooks.mark_processed(db, row, error=resolve_error)
        db.commit()
        return LabelDecision(False, reason=resolve_error)

    added = _added_labels(payload)
    decision = evaluate_labels(current_labels=current_labels, added_labels=added)
    if not decision.should_dispatch or decision.mode is None:
        inbound_webhooks.mark_processed(db, row)
        db.commit()
        logger.info("delivery_id=%s skip: %s", delivery_id, decision.reason)
        return decision

    if _has_active_run(db, card_public_id=card_public_id, mode=decision.mode):
        inbound_webhooks.mark_processed(db, row)
        db.commit()
        reason = f"active {decision.mode} run already exists for card"
        logger.info("delivery_id=%s skip: %s", delivery_id, reason)
        return LabelDecision(False, mode=decision.mode, reason=reason)

    title = str((card or {}).get("title") or (payload.get("object") or {}).get("label") or "")
    description = None if card is None else card.get("description")
    prompt = build_prompt(
        mode=decision.mode,
        title=title,
        description=description if isinstance(description, str) else None,
        card_public_id=card_public_id,
    )

    run = CursorAgentRun(
        board_public_id=row.board_public_id,
        card_public_id=card_public_id,
        mode=decision.mode,
        status="pending",
        prompt=prompt,
        source_delivery_id=delivery_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(run)
    db.flush()

    if not settings.cursor_api_key:
        run.status = "skipped"
        run.error = "CURSOR_API_KEY is not configured"
        inbound_webhooks.mark_processed(db, row, error=run.error)
        db.commit()
        return LabelDecision(False, mode=decision.mode, reason=run.error)

    if not settings.cursor_repository:
        run.status = "skipped"
        run.error = "CURSOR_REPOSITORY is not configured"
        inbound_webhooks.mark_processed(db, row, error=run.error)
        db.commit()
        return LabelDecision(False, mode=decision.mode, reason=run.error)

    run.status = "running"
    db.commit()

    try:
        result = CursorClient(runtime="cloud").prompt_once(prompt, repository=settings.cursor_repository)
    except CursorClientError as error:
        run.status = "error"
        run.error = str(error)[:500]
        run.updated_at = utc_now()
        inbound_webhooks.mark_processed(db, row, error=run.error)
        db.commit()
        logger.exception("Cursor launch failed delivery_id=%s", delivery_id)
        return LabelDecision(False, mode=decision.mode, reason=run.error)

    run.cursor_agent_id = result.agent_id
    run.cursor_run_id = result.run_id
    run.status = result.status or "finished"
    run.result_text = result.result_text
    run.updated_at = utc_now()
    inbound_webhooks.mark_processed(db, row)
    db.commit()
    logger.info(
        "launched cursor mode=%s delivery_id=%s agent=%s run=%s status=%s",
        decision.mode,
        delivery_id,
        result.agent_id,
        result.run_id,
        run.status,
    )
    return decision
