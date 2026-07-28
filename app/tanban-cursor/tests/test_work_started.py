"""Helpers and comments for c-work start notification."""

from unittest.mock import MagicMock

from services.cursor_client import (
    AgentStartInfo,
    branch_browse_url,
    normalize_repo_https_url,
    work_started_comment_text,
)
from services.dispatch import _post_work_started_comment
from services.tanban_client import TanbanClientError


def test_normalize_repo_https_url():
    assert normalize_repo_https_url("https://github.com/wotschel/tanban.git") == (
        "https://github.com/wotschel/tanban"
    )
    assert normalize_repo_https_url("github.com/wotschel/tanban") == (
        "https://github.com/wotschel/tanban"
    )


def test_branch_browse_url_encodes_slash():
    url = branch_browse_url("https://github.com/wotschel/tanban", "cursor/fix-skin")
    assert url == "https://github.com/wotschel/tanban/tree/cursor%2Ffix-skin"


def test_work_started_comment_prefers_branch_link():
    text = work_started_comment_text(
        branch="cursor/fix-skin",
        branch_url="https://github.com/wotschel/tanban/tree/cursor%2Ffix-skin",
        agent_url="https://cursor.com/agents/bc-1",
    )
    assert text.startswith("Arbeit begonnen:")
    assert "[cursor/fix-skin](" in text
    assert "cursor%2Ffix-skin" in text


def test_work_started_comment_falls_back_to_agent_link():
    text = work_started_comment_text(
        branch=None,
        branch_url=None,
        agent_url="https://cursor.com/agents/bc-1",
    )
    assert text == "Arbeit begonnen: [Cursor Agent](https://cursor.com/agents/bc-1)"


def test_post_work_started_comment_posts_markdown():
    client = MagicMock()
    info = AgentStartInfo(
        agent_id="bc-1",
        run_id="run-1",
        agent_url="https://cursor.com/agents/bc-1",
        branch="cursor/x",
        branch_url="https://github.com/org/repo/tree/cursor%2Fx",
    )
    err, fatal = _post_work_started_comment(client, card={"id": 33}, info=info)
    assert err is None
    assert fatal is False
    client.add_comment.assert_called_once()
    args = client.add_comment.call_args.args
    assert args[0] == 33
    assert "Arbeit begonnen" in args[1]
    assert "cursor/x" in args[1]


def test_post_work_started_comment_api_error_not_fatal():
    client = MagicMock()
    client.add_comment.side_effect = TanbanClientError("boom")
    info = AgentStartInfo(
        agent_id="bc-1",
        run_id=None,
        agent_url="https://cursor.com/agents/bc-1",
    )
    err, fatal = _post_work_started_comment(client, card={"id": 1}, info=info)
    assert err == "boom"
    assert fatal is False
