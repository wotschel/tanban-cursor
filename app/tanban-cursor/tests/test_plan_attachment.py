"""c-plan result upload as TanBan card attachment."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from services.dispatch import _post_plan_attachment, plan_attachment_filename
from services.tanban_client import TanbanClientError


def test_plan_attachment_filename_uses_utc_stamp():
    when = datetime(2026, 7, 28, 14, 43, 12, tzinfo=UTC)
    assert plan_attachment_filename(when=when) == "cursor-plan-20260728T144312Z.md"


def test_post_plan_attachment_uploads_markdown():
    client = MagicMock()
    card = {"id": 42}
    err, fatal = _post_plan_attachment(client, card=card, result_text="## Plan\n\nDo X")
    assert err is None
    assert fatal is False
    client.upload_card_attachment.assert_called_once()
    kwargs = client.upload_card_attachment.call_args
    assert kwargs.args[0] == 42
    assert kwargs.kwargs["filename"].startswith("cursor-plan-")
    assert kwargs.kwargs["filename"].endswith(".md")
    assert kwargs.kwargs["content"] == b"## Plan\n\nDo X"
    assert kwargs.kwargs["content_type"] == "text/markdown"


def test_post_plan_attachment_missing_text_is_fatal():
    err, fatal = _post_plan_attachment(MagicMock(), card={"id": 1}, result_text="  ")
    assert fatal is True
    assert "no result text" in err


def test_post_plan_attachment_api_error_is_not_fatal():
    client = MagicMock()
    client.upload_card_attachment.side_effect = TanbanClientError("boom")
    err, fatal = _post_plan_attachment(client, card={"id": 1}, result_text="plan body")
    assert fatal is False
    assert err == "boom"


def test_post_plan_attachment_missing_card_id_is_fatal():
    err, fatal = _post_plan_attachment(MagicMock(), card={}, result_text="plan body")
    assert fatal is True
    assert "card id" in err
