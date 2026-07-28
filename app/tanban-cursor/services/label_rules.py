"""Label rules for TanBan → Cursor dispatch.

Flow: label ``cursor`` must be set, plus ``plan`` or ``work``.
``work`` wins if both mode labels are present.
"""

from __future__ import annotations

from dataclasses import dataclass

LABEL_CURSOR = "cursor"
LABEL_PLAN = "plan"
LABEL_WORK = "work"
MODE_LABELS = frozenset({LABEL_PLAN, LABEL_WORK})

# Events that can newly establish the cursor+mode label combo.
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
    """Return ``work``, ``plan``, or None. ``work`` takes precedence."""
    if LABEL_WORK in labels:
        return LABEL_WORK
    if LABEL_PLAN in labels:
        return LABEL_PLAN
    return None


def evaluate_labels(*, current_labels: set[str], added_labels: set[str]) -> LabelDecision:
    """Decide whether this webhook should launch a Cursor cloud agent.

    Requires ``cursor`` plus ``plan`` or ``work`` on the card *after* the change.
    Fires only when at least one of those required labels was in ``added`` for
    this delivery (avoids re-dispatch on unrelated label edits).
    """
    if LABEL_CURSOR not in current_labels:
        return LabelDecision(False, reason="label cursor not set")

    mode = resolve_mode(current_labels)
    if mode is None:
        return LabelDecision(False, reason="neither plan nor work set")

    required = {LABEL_CURSOR, mode}
    if not (required & added_labels):
        return LabelDecision(
            False,
            mode=mode,
            reason="cursor+mode already set; no relevant label added",
        )

    return LabelDecision(True, mode=mode, reason=f"dispatch mode={mode}")


def build_prompt(*, mode: str, title: str, description: str | None, card_public_id: str | None) -> str:
    card_ref = card_public_id or "(unknown)"
    body = (description or "").strip() or "(no description)"
    title_text = title.strip() or "(untitled)"
    if mode == LABEL_PLAN:
        return (
            "Create a concrete implementation plan for this TanBan card. "
            "Do not implement code yet; produce steps, risks, and suggested files.\n\n"
            f"Card public_id: {card_ref}\n"
            f"Title: {title_text}\n"
            f"Description:\n{body}\n"
        )
    return (
        "Implement this TanBan card in the repository. "
        "Make focused changes, keep the diff small, and summarize what you did.\n\n"
        f"Card public_id: {card_ref}\n"
        f"Title: {title_text}\n"
        f"Description:\n{body}\n"
    )
