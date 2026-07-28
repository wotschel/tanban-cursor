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


def card_content_hash(*, mode: str, title: str, description: str | None) -> str:
    """Stable SHA-256 fingerprint of mode + card title/description.

    Used to skip re-dispatch when a mode label is removed and re-added without
    content changes. Independent of prompt template wording.
    """
    title_norm = (title or "").strip()
    body_norm = (description or "").strip()
    payload = f"{mode}\n{title_norm}\n{body_norm}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_prompt(*, mode: str, title: str, description: str | None, card_public_id: str | None) -> str:
    card_ref = card_public_id or "(unknown)"
    body = (description or "").strip() or "(no description)"
    title_text = title.strip() or "(untitled)"
    card_block = (
        f"Card public_id: {card_ref}\n"
        f"Title: {title_text}\n"
        f"Description:\n{body}\n"
    )
    if mode == LABEL_ASK:
        return (
            "Answer the question on this TanBan card. You may read the codebase for context. "
            "Do not implement code and do not produce an implementation plan. "
            "Write a clear, concise answer; it will be posted as a comment on the ticket.\n\n"
            f"{card_block}"
        )
    if mode == LABEL_PLAN:
        return (
            "Create a concrete implementation plan for this TanBan card. "
            "Do not implement code yet; produce steps, risks, and suggested files.\n\n"
            f"{card_block}"
        )
    return (
        "Implement this TanBan card in the repository. "
        "Make focused changes, keep the diff small, and summarize what you did.\n\n"
        f"{card_block}"
    )
