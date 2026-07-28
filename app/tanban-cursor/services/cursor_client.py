"""Cursor agent integration via cursor-sdk (cloud/local)."""

from __future__ import annotations

from dataclasses import dataclass

from config import settings


class CursorClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentLaunchResult:
    agent_id: str | None
    run_id: str | None
    status: str
    result_text: str | None = None


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

    def prompt_once(self, prompt: str, *, repository: str | None = None) -> AgentLaunchResult:
        """Fire-and-forget Agent.prompt. Prefer cloud for server-side bridge runs."""
        api_key = self._require_key()
        try:
            from cursor_sdk import (
                Agent,
                AgentOptions,
                CloudAgentOptions,
                CloudRepository,
                LocalAgentOptions,
            )
        except ImportError as error:
            raise CursorClientError("cursor-sdk is not installed") from error

        options_kwargs: dict = {"api_key": api_key, "model": self.model}
        if self.runtime == "cloud":
            if not repository:
                raise CursorClientError("cloud runtime requires a repository URL")
            options_kwargs["cloud"] = CloudAgentOptions(repos=[CloudRepository(url=repository)])
        else:
            options_kwargs["local"] = LocalAgentOptions(cwd=".")

        try:
            result = Agent.prompt(prompt, AgentOptions(**options_kwargs))
        except Exception as error:  # noqa: BLE001 — surface SDK failures as domain errors
            raise CursorClientError(f"Cursor agent failed to start: {error}") from error

        return AgentLaunchResult(
            agent_id=str(result.agent_id) if result.agent_id else None,
            run_id=str(result.id) if result.id else None,
            status=str(result.status),
            result_text=str(result.result) if result.result is not None else None,
        )
