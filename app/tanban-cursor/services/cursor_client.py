"""Cursor agent integration via cursor-sdk (cloud/local)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

from config import settings

logger = logging.getLogger("tanban-cursor.cursor")


class CursorClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentStartInfo:
    """Fired when a cloud work agent is running and (ideally) has a branch."""

    agent_id: str
    run_id: str | None
    agent_url: str
    branch: str | None = None
    branch_url: str | None = None
    pr_url: str | None = None


@dataclass(frozen=True)
class AgentLaunchResult:
    agent_id: str | None
    run_id: str | None
    status: str
    result_text: str | None = None
    branch: str | None = None
    branch_url: str | None = None
    pr_url: str | None = None


def normalize_repo_https_url(repository: str) -> str:
    """Return an https:// repo URL without trailing .git or slash."""
    raw = (repository or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    path = (parsed.path or "").rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    netloc = parsed.netloc
    if not netloc:
        # urlparse("github.com/org/repo") puts all in path
        parts = (parsed.path or "").lstrip("/").split("/", 1)
        netloc = parts[0]
        path = "/" + parts[1] if len(parts) > 1 else ""
        if path.endswith(".git"):
            path = path[:-4]
    return f"https://{netloc}{path}"


def branch_browse_url(repository: str, branch: str) -> str:
    """GitHub/GitLab tree URL for ``branch`` under ``repository``."""
    base = normalize_repo_https_url(repository)
    if not base or not branch:
        return ""
    return f"{base}/tree/{quote(branch, safe='')}"


def agent_web_url(agent_id: str) -> str:
    return f"https://cursor.com/agents/{agent_id}"


def _first_branch_info(git: Any) -> tuple[str | None, str | None, str | None]:
    """Return ``(branch, repo_url_hint, pr_url)`` from SDK/REST git payload."""
    if git is None:
        return None, None, None
    branches = getattr(git, "branches", None)
    if branches is None and isinstance(git, dict):
        branches = git.get("branches")
    if not branches:
        return None, None, None
    first = branches[0]
    if isinstance(first, dict):
        branch = first.get("branch") or None
        repo_url = first.get("repo_url") or first.get("repoUrl") or None
        pr_url = first.get("pr_url") or first.get("prUrl") or None
    else:
        branch = getattr(first, "branch", None) or None
        repo_url = getattr(first, "repo_url", None) or None
        pr_url = getattr(first, "pr_url", None) or None
    return (
        str(branch) if branch else None,
        str(repo_url) if repo_url else None,
        str(pr_url) if pr_url else None,
    )


def work_started_comment_text(*, branch: str | None, branch_url: str | None, agent_url: str) -> str:
    """Build the TanBan comment body for a started c-work run."""
    if branch and branch_url:
        return f"Arbeit begonnen: [{branch}]({branch_url})"
    if branch:
        return f"Arbeit begonnen: `{branch}`"
    return f"Arbeit begonnen: [Cursor Agent]({agent_url})"


class CursorClient:
    """Thin wrapper around cursor-sdk. Cloud is the default runtime for this bridge."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        runtime: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.cursor_api_key
        self.model = model if model is not None else settings.cursor_model
        self.runtime = (runtime if runtime is not None else settings.cursor_runtime).casefold()

    def _require_key(self) -> str:
        if not self.api_key:
            raise CursorClientError("CURSOR_API_KEY is not configured")
        return self.api_key

    def _cloud_options(self, repository: str, *, auto_create_pr: bool):
        from cursor_sdk import CloudAgentOptions, CloudRepository

        return CloudAgentOptions(
            repos=[CloudRepository(url=repository)],
            auto_create_pr=auto_create_pr,
        )

    def prompt_once(self, prompt: str, *, repository: str | None = None) -> AgentLaunchResult:
        """Fire-and-forget Agent.prompt. Prefer cloud for server-side bridge runs."""
        api_key = self._require_key()
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
        except ImportError as error:
            raise CursorClientError("cursor-sdk is not installed") from error

        options_kwargs: dict = {"api_key": api_key, "model": self.model}
        if self.runtime == "cloud":
            if not repository:
                raise CursorClientError("cloud runtime requires a repository URL")
            options_kwargs["cloud"] = self._cloud_options(repository, auto_create_pr=False)
        else:
            options_kwargs["local"] = LocalAgentOptions(cwd=".")

        try:
            result = Agent.prompt(prompt, AgentOptions(**options_kwargs))
        except Exception as error:  # noqa: BLE001 — surface SDK failures as domain errors
            raise CursorClientError(f"Cursor agent failed to start: {error}") from error

        branch, repo_hint, pr_url = _first_branch_info(getattr(result, "git", None))
        branch_url = None
        if branch:
            branch_url = branch_browse_url(repo_hint or repository or "", branch) or None

        return AgentLaunchResult(
            agent_id=str(result.agent_id) if result.agent_id else None,
            run_id=str(result.id) if result.id else None,
            status=str(result.status),
            result_text=str(result.result) if result.result is not None else None,
            branch=branch,
            branch_url=branch_url,
            pr_url=pr_url,
        )

    def prompt_work(
        self,
        prompt: str,
        *,
        repository: str,
        on_launch: Callable[[str, str | None], None] | None = None,
        on_started: Callable[[AgentStartInfo], None] | None = None,
        branch_poll_interval_s: float = 2.0,
    ) -> AgentLaunchResult:
        """Create a cloud agent for c-work, notify when a branch exists, then wait.

        ``on_launch`` runs on the caller thread right after ``send`` (agent/run ids).
        ``on_started`` is called at most once: as soon as ``git.branches`` is visible
        while the run is active, or as a fallback after ``wait()`` (branch and/or
        agent URL). It may run on a background poller thread — keep it free of
        shared SQLAlchemy sessions.
        """
        api_key = self._require_key()
        if self.runtime != "cloud":
            raise CursorClientError("c-work requires cloud runtime")
        if not repository:
            raise CursorClientError("cloud runtime requires a repository URL")

        try:
            from cursor_sdk import Agent
        except ImportError as error:
            raise CursorClientError("cursor-sdk is not installed") from error

        started_lock = threading.Lock()
        started_sent = False

        def notify(info: AgentStartInfo) -> None:
            nonlocal started_sent
            with started_lock:
                if started_sent:
                    return
                started_sent = True
            if on_started is None:
                return
            try:
                on_started(info)
            except Exception:  # noqa: BLE001 — never fail the agent wait on comment side effects
                logger.exception("on_started callback failed agent_id=%s", info.agent_id)

        try:
            with Agent.create(
                api_key=api_key,
                model=self.model,
                cloud=self._cloud_options(repository, auto_create_pr=True),
            ) as agent:
                cursor_run = agent.send(prompt)
                agent_id = str(agent.agent_id)
                run_id = str(getattr(cursor_run, "id", None) or getattr(cursor_run, "run_id", None) or "") or None
                if on_launch is not None:
                    try:
                        on_launch(agent_id, run_id)
                    except Exception:  # noqa: BLE001 — launch bookkeeping must not abort the agent
                        logger.exception("on_launch callback failed agent_id=%s", agent_id)

                stop = threading.Event()

                def poll_for_branch() -> None:
                    while not stop.wait(branch_poll_interval_s):
                        with started_lock:
                            if started_sent:
                                return
                        try:
                            live = Agent.get_run(str(run_id)) if run_id else None
                            git = getattr(live, "git", None) if live is not None else None
                            branch, repo_hint, pr_url = _first_branch_info(git)
                            if not branch:
                                continue
                            branch_url = branch_browse_url(repo_hint or repository, branch) or None
                            notify(
                                AgentStartInfo(
                                    agent_id=agent_id,
                                    run_id=run_id,
                                    agent_url=agent_web_url(agent_id),
                                    branch=branch,
                                    branch_url=branch_url,
                                    pr_url=pr_url,
                                )
                            )
                            return
                        except Exception:  # noqa: BLE001 — keep polling until wait ends
                            logger.debug("branch poll failed run_id=%s", run_id, exc_info=True)

                poller = threading.Thread(target=poll_for_branch, name="cursor-branch-poll", daemon=True)
                poller.start()
                try:
                    result = cursor_run.wait()
                finally:
                    stop.set()
                    poller.join(timeout=max(branch_poll_interval_s * 2, 5.0))

                branch, repo_hint, pr_url = _first_branch_info(getattr(result, "git", None))
                branch_url = branch_browse_url(repo_hint or repository, branch) if branch else None
                notify(
                    AgentStartInfo(
                        agent_id=str(result.agent_id or agent_id),
                        run_id=str(result.id) if result.id else run_id,
                        agent_url=agent_web_url(str(result.agent_id or agent_id)),
                        branch=branch,
                        branch_url=branch_url or None,
                        pr_url=pr_url,
                    )
                )
                return AgentLaunchResult(
                    agent_id=str(result.agent_id) if result.agent_id else agent_id,
                    run_id=str(result.id) if result.id else run_id,
                    status=str(result.status),
                    result_text=str(result.result) if result.result is not None else None,
                    branch=branch,
                    branch_url=branch_url or None,
                    pr_url=pr_url,
                )
        except CursorClientError:
            raise
        except Exception as error:  # noqa: BLE001 — surface SDK failures as domain errors
            raise CursorClientError(f"Cursor work agent failed: {error}") from error
