"""Comments for c-work start/finish and Cursor: prefix."""

from unittest.mock import MagicMock

from services.cursor_client import (
    AgentLaunchResult,
    AgentStartInfo,
    branch_browse_url,
    normalize_repo_https_url,
    work_finished_comment_text,
    work_started_comment_text,
)
from services.dispatch import _post_work_finished_comment, _post_work_started_comment
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
    assert text.startswith("Cursor: Arbeit begonnen:")
    assert "[cursor/fix-skin](" in text


def test_work_started_comment_falls_back_to_agent_link():
    text = work_started_comment_text(
        branch=None,
        branch_url=None,
        agent_url="https://cursor.com/agents/bc-1",
    )
    assert text == "Cursor: Arbeit begonnen: [Cursor Agent](https://cursor.com/agents/bc-1)"


def test_work_finished_comment_includes_summary_and_pr():
    text = work_finished_comment_text(
        result_text="Fixed button styling.",
        branch="cursor/x",
        branch_url="https://github.com/org/repo/tree/cursor%2Fx",
        pr_url="https://github.com/org/repo/pull/12",
    )
    assert text.startswith("Cursor: Arbeit beendet")
    assert "PR: https://github.com/org/repo/pull/12" in text
    assert "Fixed button styling." in text


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
    args = client.add_comment.call_args.args
    assert args[0] == 33
    assert args[1].startswith("Cursor: Arbeit begonnen:")


def test_post_work_finished_comment_posts_markdown():
    client = MagicMock()
    result = AgentLaunchResult(
        agent_id="bc-1",
        run_id="run-1",
        status="finished",
        result_text="Done.",
        branch="cursor/x",
        branch_url="https://github.com/org/repo/tree/cursor%2Fx",
    )
    err, fatal = _post_work_finished_comment(client, card={"id": 33}, result=result)
    assert err is None
    assert fatal is False
    args = client.add_comment.call_args.args
    assert args[1].startswith("Cursor: Arbeit beendet")
    assert "Done." in args[1]


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


def test_prompt_work_posts_start_before_wait(monkeypatch):
    """Start callback must run before wait() returns (agent-link fallback)."""
    from services.cursor_client import CursorClient

    events: list[str] = []

    class FakeRun:
        id = "run-1"
        agent_id = "bc-1"
        status = "finished"
        result = "done"
        git = None

        def wait(self):
            events.append("wait")
            return self

    class FakeAgent:
        agent_id = "bc-1"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send(self, _prompt):
            events.append("send")
            return FakeRun()

    class FakeAgentModule:
        @staticmethod
        def create(**_kwargs):
            return FakeAgent()

        @staticmethod
        def get_run(_run_id):
            raise RuntimeError("get_run unavailable")

    monkeypatch.setitem(__import__("sys").modules, "cursor_sdk", MagicMock(Agent=FakeAgentModule))
    # CursorClient imports Agent from cursor_sdk inside the method
    import services.cursor_client as cursor_mod

    monkeypatch.setattr(
        cursor_mod,
        "settings",
        MagicMock(cursor_api_key="k", cursor_model="m", cursor_runtime="cloud"),
    )

    client = CursorClient(api_key="k", model="m", runtime="cloud")

    def on_started(_info):
        events.append("started")

    result = client.prompt_work(
        "do it",
        repository="https://github.com/org/repo",
        on_started=on_started,
        early_branch_timeout_s=0.0,
        branch_poll_interval_s=0.01,
    )

    assert events == ["send", "started", "wait"]
    assert result.status == "finished"
    assert result.agent_id == "bc-1"


def test_prompt_work_prefers_early_branch(monkeypatch):
    from types import SimpleNamespace

    from services.cursor_client import CursorClient
    import services.cursor_client as cursor_mod

    started: list = []

    class FakeRun:
        id = "run-1"
        agent_id = "bc-1"
        status = "finished"
        result = "done"
        git = SimpleNamespace(branches=[SimpleNamespace(branch="cursor/x", repo_url=None, pr_url=None)])

        def wait(self):
            return self

    class FakeAgent:
        agent_id = "bc-1"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send(self, _prompt):
            return FakeRun()

    class FakeAgentModule:
        @staticmethod
        def create(**_kwargs):
            return FakeAgent()

        @staticmethod
        def get_run(_run_id):
            return SimpleNamespace(
                git=SimpleNamespace(
                    branches=[{"branch": "cursor/x", "repo_url": "https://github.com/org/repo"}]
                )
            )

    monkeypatch.setitem(__import__("sys").modules, "cursor_sdk", MagicMock(Agent=FakeAgentModule))
    monkeypatch.setattr(
        cursor_mod,
        "settings",
        MagicMock(cursor_api_key="k", cursor_model="m", cursor_runtime="cloud"),
    )

    client = CursorClient(api_key="k", model="m", runtime="cloud")
    client.prompt_work(
        "do it",
        repository="https://github.com/org/repo",
        on_started=lambda info: started.append(info),
        early_branch_timeout_s=1.0,
        branch_poll_interval_s=0.01,
    )

    assert len(started) == 1
    assert started[0].branch == "cursor/x"
    assert started[0].branch_url is not None
