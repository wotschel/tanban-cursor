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
    LABEL_ASK,
    LabelDecision,
    blocked_reason_for_mode,
    build_prompt,
    card_content_hash,
    evaluate_labels,
    normalize_label_names,
)
from services.tanban_boards import LegacyBoardBinding, TanbanBoardConfig
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
    board: TanbanBoardConfig | LegacyBoardBinding,
    card_public_id: str,
    payload: dict[str, Any],
    event: str,
) -> tuple[dict[str, Any] | None, set[str], str | None]:
    """Return (card_or_none, current_label_names, error)."""
    if board.board_id is not None:
        try:
            card = client.find_card_by_public_id(board.board_id, card_public_id)
        except TanbanClientError as error:
            return None, set(), str(error)
        if card is None:
            return None, set(), f"card public_id={card_public_id} not found on board {board.board_id}"
        names = normalize_label_names(
            [str(label.get("name") or "") for label in (card.get("labels") or []) if isinstance(label, dict)]
        )
        return card, names, None

    # Fallback without board id: only card_created carries the full initial set in labels.added.
    if event == "card_created":
        return None, _added_labels(payload), None
    return None, set(), "board_id is required to resolve labels for this event"


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


def _has_submitted_unchanged_run(
    db: Session,
    *,
    card_public_id: str,
    mode: str,
    content_hash: str,
) -> bool:
    """True if this card+mode+content was already handed to Cursor."""
    existing = (
        db.query(CursorAgentRun)
        .filter(
            CursorAgentRun.card_public_id == card_public_id,
            CursorAgentRun.mode == mode,
            CursorAgentRun.content_hash == content_hash,
            CursorAgentRun.cursor_agent_id.isnot(None),
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

    board = settings.resolve_board(row.board_public_id)
    if board is None:
        reason = f"no TanBan credentials configured for board public_id={row.board_public_id or '-'}"
        inbound_webhooks.mark_processed(db, row, error=reason)
        db.commit()
        return LabelDecision(False, reason=reason)

    client = TanbanClient(api_key=board.api_key)
    card, current_labels, resolve_error = _resolve_card(
        client,
        board=board,
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
    description_text = description if isinstance(description, str) else None
    content_hash = card_content_hash(
        mode=decision.mode,
        title=title,
        description=description_text,
    )

    if _has_submitted_unchanged_run(
        db,
        card_public_id=card_public_id,
        mode=decision.mode,
        content_hash=content_hash,
    ):
        inbound_webhooks.mark_processed(db, row)
        db.commit()
        reason = f"unchanged {decision.mode} content already submitted to Cursor"
        logger.info("delivery_id=%s skip: %s", delivery_id, reason)
        return LabelDecision(False, mode=decision.mode, reason=reason)

    prompt = build_prompt(
        mode=decision.mode,
        title=title,
        description=description_text,
        card_public_id=card_public_id,
    )

    run = CursorAgentRun(
        board_public_id=row.board_public_id,
        card_public_id=card_public_id,
        mode=decision.mode,
        content_hash=content_hash,
        status="pending",
        prompt=prompt,
        source_delivery_id=delivery_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    db.add(run)
    db.flush()

    if not settings.cursor_active:
        run.status = "skipped"
        run.error = "CURSOR_ACTIVE is false (dry-run)"
        inbound_webhooks.mark_processed(db, row)
        db.commit()
        logger.info(
            "CURSOR_ACTIVE=false dry-run mode=%s delivery_id=%s card=%s title=%r prompt_chars=%s",
            decision.mode,
            delivery_id,
            card_public_id,
            title,
            len(prompt),
        )
        return LabelDecision(False, mode=decision.mode, reason=run.error)

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

    block_error = _block_card_for_mode(client, card=card, mode=decision.mode)
    if block_error:
        run.status = "error"
        run.error = block_error[:500]
        run.updated_at = utc_now()
        inbound_webhooks.mark_processed(db, row, error=run.error)
        db.commit()
        logger.warning("card block failed delivery_id=%s: %s", delivery_id, block_error)
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

    if decision.mode == LABEL_ASK:
        comment_error, fatal = _post_ask_comment(client, card=card, result_text=result.result_text)
        if comment_error:
            run.error = comment_error[:500]
            if fatal:
                run.status = "error"
            run.updated_at = utc_now()
            inbound_webhooks.mark_processed(db, row, error=run.error)
            db.commit()
            logger.warning("ask comment failed delivery_id=%s: %s", delivery_id, comment_error)
            return LabelDecision(False, mode=decision.mode, reason=run.error)

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


def _block_card_for_mode(
    client: TanbanClient,
    *,
    card: dict[str, Any] | None,
    mode: str,
) -> str | None:
    """Mark the TanBan card blocked while Cursor works. Return error or None."""
    if not isinstance(card, dict) or card.get("id") is None:
        return "blocking requires card id from board card lookup"
    try:
        card_id = int(card["id"])
    except (TypeError, ValueError):
        return f"blocking got invalid card id: {card.get('id')!r}"
    reason = blocked_reason_for_mode(mode)
    try:
        client.set_card_blocked(card_id, reason=reason)
    except TanbanClientError as error:
        return str(error)
    return None


def _post_ask_comment(
    client: TanbanClient,
    *,
    card: dict[str, Any] | None,
    result_text: str | None,
) -> tuple[str | None, bool]:
    """Post ask result as a TanBan card comment.

    Returns ``(error_message_or_none, fatal)``. ``fatal`` means the run should be
    marked ``error`` (missing text/card id); API post failures keep Cursor status.
    """
    if not result_text or not str(result_text).strip():
        return "ask mode produced no result text to post as comment", True
    if not isinstance(card, dict) or card.get("id") is None:
        return "ask mode requires card id from board card lookup to post comment", True
    try:
        card_id = int(card["id"])
    except (TypeError, ValueError):
        return f"ask mode got invalid card id: {card.get('id')!r}", True
    text = f"Cursor ask:\n\n{str(result_text).strip()}"
    try:
        client.add_comment(card_id, text)
    except TanbanClientError as error:
        return str(error), False
    return None, False

