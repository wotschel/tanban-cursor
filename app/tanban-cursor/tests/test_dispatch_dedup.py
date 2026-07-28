"""Content-dedup helpers used before launching Cursor."""

from unittest.mock import MagicMock

from services.dispatch import _has_submitted_unchanged_run
from services.label_rules import card_content_hash


def test_has_submitted_unchanged_run_true_when_row_exists():
    db = MagicMock()
    query = db.query.return_value
    filtered = query.filter.return_value
    filtered.first.return_value = object()

    content_hash = card_content_hash(mode="c-plan", title="Ship it", description="Do X")
    assert (
        _has_submitted_unchanged_run(
            db,
            card_public_id="card-1",
            mode="c-plan",
            content_hash=content_hash,
        )
        is True
    )
    db.query.assert_called_once()


def test_has_submitted_unchanged_run_false_when_no_row():
    db = MagicMock()
    query = db.query.return_value
    filtered = query.filter.return_value
    filtered.first.return_value = None

    content_hash = card_content_hash(mode="c-plan", title="Ship it", description="Do X")
    assert (
        _has_submitted_unchanged_run(
            db,
            card_public_id="card-1",
            mode="c-plan",
            content_hash=content_hash,
        )
        is False
    )


def test_c_plan_toggle_same_content_hash_is_identical():
    """Remove/re-add c-plan without edits yields the same fingerprint."""
    first = card_content_hash(mode="c-plan", title="Plan me", description="Steps")
    again = card_content_hash(mode="c-plan", title="Plan me", description="Steps")
    assert first == again


def test_c_plan_edit_before_readd_changes_hash():
    before = card_content_hash(mode="c-plan", title="Plan me", description="Steps")
    after = card_content_hash(mode="c-plan", title="Plan me", description="Steps v2")
    assert before != after
