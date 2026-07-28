"""Dispatch TanBan webhook events to Cursor cloud when labels match."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from config import settings
from models import CursorAgentRun, InboundWebhookEvent
from services import inbound_webhooks
from services.cursor_client import (
    AgentStartInfo,
    AgentLaunchResult,
    CursorClient,
    CursorClientError,
    work_finished_comment_text,
    work_started_comment_text,
)
from services.label_rules import (
    DISPATCH_EVENTS,
    LABEL_ASK,
    LABEL_PLAN,
    LABEL_WORK,
    LabelDecision,
    blocked_reason_for_mode,
    build_prompt,
    card_content_hash,
    evaluate_labels,
    normalize_checklist_items,
    normalize_comment_texts,
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

    comment_texts: list[str] = []
    checklist_items: list[tuple[str, bool]] = []
    card_id = _card_numeric_id(card)
    if card_id is not None:
        try:
            comment_texts = normalize_comment_texts(client.list_comments(card_id))
            checklist_items = normalize_checklist_items(client.list_checklist_items(card_id))
        except TanbanClientError as error:
            inbound_webhooks.mark_processed(db, row, error=str(error))
            db.commit()
            logger.warning("delivery_id=%s skip: failed loading card substance: %s", delivery_id, error)
            return LabelDecision(False, mode=decision.mode, reason=str(error))

    content_hash = card_content_hash(
        mode=decision.mode,
        title=title,
        description=description_text,
        comments=comment_texts,
        checklist_items=checklist_items,
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
        comments=comment_texts,
        checklist_items=checklist_items,
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

    work_started_error: str | None = None

    def _on_work_launch(agent_id: str, run_id: str | None) -> None:
        run.cursor_agent_id = agent_id
        if run_id:
            run.cursor_run_id = run_id
        run.updated_at = utc_now()
        db.commit()

    def _on_work_started(info: AgentStartInfo) -> None:
        nonlocal work_started_error
        comment_error, _fatal = _post_work_started_comment(client, card=card, info=info)
        if comment_error:
            work_started_error = comment_error
            logger.warning("work started comment failed delivery_id=%s: %s", delivery_id, comment_error)

    try:
        cursor = CursorClient(runtime="cloud")
        if decision.mode == LABEL_WORK:
            result = cursor.prompt_work(
                prompt,
                repository=settings.cursor_repository,
                on_launch=_on_work_launch,
                on_started=_on_work_started,
            )
        else:
            result = cursor.prompt_once(prompt, repository=settings.cursor_repository)
    except CursorClientError as error:
        run.status = "error"
        run.error = str(error)[:500]
        run.updated_at = utc_now()
        inbound_webhooks.mark_processed(db, row, error=run.error)
        db.commit()
        logger.exception("Cursor launch failed delivery_id=%s", delivery_id)
        return LabelDecision(False, mode=decision.mode, reason=run.error)

    run.cursor_agent_id = result.agent_id or run.cursor_agent_id
    run.cursor_run_id = result.run_id or run.cursor_run_id
    run.status = result.status or "finished"
    run.result_text = result.result_text
    run.updated_at = utc_now()
    if work_started_error and not run.error:
        run.error = work_started_error[:500]

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

    if decision.mode == LABEL_PLAN:
        attach_error, fatal = _post_plan_attachment(client, card=card, result_text=result.result_text)
        if attach_error:
            run.error = attach_error[:500]
            if fatal:
                run.status = "error"
            run.updated_at = utc_now()
            inbound_webhooks.mark_processed(db, row, error=run.error)
            db.commit()
            logger.warning("plan attachment failed delivery_id=%s: %s", delivery_id, attach_error)
            return LabelDecision(False, mode=decision.mode, reason=run.error)

    if decision.mode == LABEL_WORK:
        finish_error, fatal = _post_work_finished_comment(client, card=card, result=result)
        if finish_error:
            if not run.error:
                run.error = finish_error[:500]
            if fatal:
                run.status = "error"
            run.updated_at = utc_now()
            inbound_webhooks.mark_processed(db, row, error=run.error)
            db.commit()
            logger.warning("work finished comment failed delivery_id=%s: %s", delivery_id, finish_error)
            return LabelDecision(False, mode=decision.mode, reason=run.error)

        unblock_error = _unblock_card(client, card=card)
        if unblock_error:
            run.error = unblock_error[:500]
            run.updated_at = utc_now()
            inbound_webhooks.mark_processed(db, row, error=run.error)
            db.commit()
            logger.warning("work unblock failed delivery_id=%s: %s", delivery_id, unblock_error)
            return LabelDecision(False, mode=decision.mode, reason=run.error)

    inbound_webhooks.mark_processed(db, row)
    db.commit()
    logger.info(
        "launched cursor mode=%s delivery_id=%s agent=%s run=%s status=%s branch=%s",
        decision.mode,
        delivery_id,
        result.agent_id,
        result.run_id,
        run.status,
        result.branch or "-",
    )
    return decision


def _card_numeric_id(card: dict[str, Any] | None) -> int | None:
    if not isinstance(card, dict) or card.get("id") is None:
        return None
    try:
        return int(card["id"])
    except (TypeError, ValueError):
        return None


def _block_card_for_mode(
    client: TanbanClient,
    *,
    card: dict[str, Any] | None,
    mode: str,
) -> str | None:
    """Mark the TanBan card blocked while Cursor works. Return error or None."""
    card_id = _card_numeric_id(card)
    if card_id is None:
        return "blocking requires card id from board card lookup"
    reason = blocked_reason_for_mode(mode)
    try:
        client.set_card_blocked(card_id, reason=reason)
    except TanbanClientError as error:
        return str(error)
    return None


def _unblock_card(client: TanbanClient, *, card: dict[str, Any] | None) -> str | None:
    """Clear TanBan card block after Cursor work. Return error or None."""
    card_id = _card_numeric_id(card)
    if card_id is None:
        return "unblocking requires card id from board card lookup"
    try:
        client.set_card_unblocked(card_id)
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
    card_id = _card_numeric_id(card)
    if card_id is None:
        return "ask mode requires card id from board card lookup to post comment", True
    text = f"Cursor:\n\n{str(result_text).strip()}"
    try:
        client.add_comment(card_id, text)
    except TanbanClientError as error:
        return str(error), False
    return None, False


def _post_work_started_comment(
    client: TanbanClient,
    *,
    card: dict[str, Any] | None,
    info: AgentStartInfo,
) -> tuple[str | None, bool]:
    """Post ``Cursor: Arbeit begonnen`` with branch (or agent) link.

    Returns ``(error_message_or_none, fatal)``. Missing card id is fatal; API
    failures keep the Cursor run status.
    """
    card_id = _card_numeric_id(card)
    if card_id is None:
        return "work mode requires card id from board card lookup to post started comment", True
    text = work_started_comment_text(
        branch=info.branch,
        branch_url=info.branch_url,
        agent_url=info.agent_url,
    )
    try:
        client.add_comment(card_id, text)
    except TanbanClientError as error:
        return str(error), False
    logger.info(
        "posted work started comment card_id=%s branch=%s agent=%s",
        card_id,
        info.branch or "-",
        info.agent_id,
    )
    return None, False


def _post_work_finished_comment(
    client: TanbanClient,
    *,
    card: dict[str, Any] | None,
    result: AgentLaunchResult,
) -> tuple[str | None, bool]:
    """Post ``Cursor: Arbeit beendet`` with optional summary/PR before unblock.

    Returns ``(error_message_or_none, fatal)``. Missing card id is fatal; API
    failures keep the Cursor run status.
    """
    card_id = _card_numeric_id(card)
    if card_id is None:
        return "work mode requires card id from board card lookup to post finished comment", True
    text = work_finished_comment_text(
        result_text=result.result_text,
        branch=result.branch,
        branch_url=result.branch_url,
        pr_url=result.pr_url,
    )
    try:
        client.add_comment(card_id, text)
    except TanbanClientError as error:
        return str(error), False
    logger.info(
        "posted work finished comment card_id=%s branch=%s agent=%s",
        card_id,
        result.branch or "-",
        result.agent_id or "-",
    )
    return None, False


def plan_attachment_filename(*, when: datetime | None = None) -> str:
    """Return ``cursor-plan-<UTC timestamp>.md`` for TanBan upload."""
    stamp = (when or utc_now()).strftime("%Y%m%dT%H%M%SZ")
    return f"cursor-plan-{stamp}.md"


def _post_plan_attachment(
    client: TanbanClient,
    *,
    card: dict[str, Any] | None,
    result_text: str | None,
) -> tuple[str | None, bool]:
    """Upload plan result as a Markdown card attachment.

    Returns ``(error_message_or_none, fatal)``. ``fatal`` means the run should be
    marked ``error`` (missing text/card id); API upload failures keep Cursor status.
    """
    if not result_text or not str(result_text).strip():
        return "plan mode produced no result text to attach", True
    card_id = _card_numeric_id(card)
    if card_id is None:
        return "plan mode requires card id from board card lookup to upload attachment", True
    filename = plan_attachment_filename()
    content = str(result_text).strip().encode("utf-8")
    try:
        client.upload_card_attachment(
            card_id,
            filename=filename,
            content=content,
            content_type="text/markdown",
        )
    except TanbanClientError as error:
        return str(error), False
    logger.info("uploaded plan attachment card_id=%s filename=%s", card_id, filename)
    return None, False

