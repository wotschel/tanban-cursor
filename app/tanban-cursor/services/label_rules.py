"""Label rules for TanBan → Cursor dispatch.

Flow: one of ``c-ask``, ``c-plan``, or ``c-work`` must be set.
Priority when multiple mode labels are present: ``c-work`` > ``c-plan`` > ``c-ask``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

LABEL_ASK = "c-ask"
LABEL_PLAN = "c-plan"
LABEL_WORK = "c-work"
MODE_LABELS = frozenset({LABEL_ASK, LABEL_PLAN, LABEL_WORK})

# Events that can newly establish a mode label.
DISPATCH_EVENTS = frozenset({"card_created", "card_labels_changed"})


@dataclass(frozen=True)
class LabelDecision:
    should_dispatch: bool
    mode: str | None = None
    reason: str = ""


def normalize_label_names(names: list[str] | None) -> set[str]:
    if not names:
        return set()
    return {name.strip().casefold() for name in names if name and name.strip()}


def resolve_mode(labels: set[str]) -> str | None:
    """Return ``c-work``, ``c-plan``, ``c-ask``, or None. ``c-work`` > ``c-plan`` > ``c-ask``."""
    if LABEL_WORK in labels:
        return LABEL_WORK
    if LABEL_PLAN in labels:
        return LABEL_PLAN
    if LABEL_ASK in labels:
        return LABEL_ASK
    return None


def blocked_reason_for_mode(mode: str) -> str:
    """TanBan ``blocked_reason`` text when handing a card to Cursor."""
    if mode == LABEL_ASK:
        return "cursor ask"
    if mode == LABEL_PLAN:
        return "cursor plan"
    if mode == LABEL_WORK:
        return "cursor work"
    return f"cursor {mode}"


def evaluate_labels(*, current_labels: set[str], added_labels: set[str]) -> LabelDecision:
    """Decide whether this webhook should launch a Cursor cloud agent.

    Requires ``c-ask``, ``c-plan``, or ``c-work`` on the card *after* the change.
    Fires only when that resolved mode label was in ``added`` for this delivery
    (avoids re-dispatch on unrelated label edits).
    """
    mode = resolve_mode(current_labels)
    if mode is None:
        return LabelDecision(False, reason="neither c-ask, c-plan, nor c-work set")

    if mode not in added_labels:
        return LabelDecision(
            False,
            mode=mode,
            reason="mode already set; no relevant label added",
        )

    return LabelDecision(True, mode=mode, reason=f"dispatch mode={mode}")


def card_content_hash(
    *,
    mode: str,
    title: str,
    description: str | None,
    comments: list[str] | None = None,
    checklist_items: list[tuple[str, bool]] | None = None,
) -> str:
    """Stable SHA-256 fingerprint of mode + card substance.

    Includes title, description, comment texts, and checklist items so that a
    new comment (or checklist change) allows re-dispatch after label toggle.
    Independent of prompt template wording.
    """
    title_norm = (title or "").strip()
    body_norm = (description or "").strip()
    comment_lines = [(c or "").strip() for c in (comments or [])]
    checklist_lines = [
        f"{'1' if done else '0'}\t{(text or '').strip()}" for text, done in (checklist_items or [])
    ]
    parts = [
        mode,
        title_norm,
        body_norm,
        "---comments---",
        *comment_lines,
        "---checklist---",
        *checklist_lines,
    ]
    payload = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_comment_texts(comments: list[dict] | None) -> list[str]:
    """Stable comment text list ordered by id ascending."""
    if not comments:
        return []
    rows: list[tuple[int, str]] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        text = comment.get("text")
        if not isinstance(text, str):
            continue
        try:
            comment_id = int(comment.get("id"))
        except (TypeError, ValueError):
            comment_id = 0
        rows.append((comment_id, text.strip()))
    rows.sort(key=lambda item: item[0])
    return [text for _, text in rows]


def normalize_checklist_items(items: list[dict] | None) -> list[tuple[str, bool]]:
    """Stable checklist (text, done) ordered by position then id."""
    if not items:
        return []
    rows: list[tuple[int, int, str, bool]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            item_id = 0
        try:
            position = int(item.get("position") or 0)
        except (TypeError, ValueError):
            position = 0
        done = bool(item.get("done"))
        rows.append((position, item_id, text.strip(), done))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [(text, done) for _, _, text, done in rows]


def build_prompt(
    *,
    mode: str,
    title: str,
    description: str | None,
    card_public_id: str | None,
    comments: list[str] | None = None,
    checklist_items: list[tuple[str, bool]] | None = None,
) -> str:
    card_ref = card_public_id or "(unknown)"
    body = (description or "").strip() or "(no description)"
    title_text = title.strip() or "(untitled)"
    comment_texts = [(c or "").strip() for c in (comments or []) if (c or "").strip()]
    if comment_texts:
        comments_block = "\n".join(f"- {text}" for text in comment_texts)
    else:
        comments_block = "(no comments)"
    checklist = list(checklist_items or [])
    if checklist:
        checklist_block = "\n".join(
            f"- [{'x' if done else ' '}] {(text or '').strip() or '(empty)'}" for text, done in checklist
        )
    else:
        checklist_block = "(no checklist items)"
    card_block = (
        f"Card public_id: {card_ref}\n"
        f"Title: {title_text}\n"
        f"Description:\n{body}\n"
        f"Comments:\n{comments_block}\n"
        f"Checklist:\n{checklist_block}\n"
    )
    if mode == LABEL_ASK:
        return (
            "Answer the question on this TanBan card. You may read the codebase for context. "
            "Do not implement code and do not produce an implementation plan. "
            "Write a clear, concise answer; it will be posted as a ticket comment prefixed with Cursor:.\n\n"
            f"{card_block}"
        )
    if mode == LABEL_PLAN:
        return (
            "Create a concrete implementation plan for this TanBan card. "
            "Do not implement code yet; produce steps, risks, and suggested files. "
            "The plan will be attached to the ticket as a Markdown file.\n\n"
            f"{card_block}"
        )
    return (
        "Implement this TanBan card in the repository. "
        "Make focused changes, keep the diff small, and summarize what you did. "
        "Push to the cloud agent branch so the ticket can link to it.\n\n"
        f"{card_block}"
    )
