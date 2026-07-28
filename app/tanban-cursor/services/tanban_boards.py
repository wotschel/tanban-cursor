"""Resolve TanBan board credentials for multi-board webhook dispatch."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class TanbanBoardsConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class TanbanBoardConfig:
    """Credentials for one TanBan board that may send webhooks to this bridge."""

    public_id: str
    board_id: int
    api_key: str
    webhook_secret: str


def normalize_public_id(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.casefold() if text else None


def parse_boards_json(raw: str) -> dict[str, TanbanBoardConfig]:
    """Parse ``TANBAN_BOARDS`` JSON object keyed by board public_id."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise TanbanBoardsConfigError(f"TANBAN_BOARDS must be valid JSON: {error}") from error
    if not isinstance(data, dict) or not data:
        raise TanbanBoardsConfigError("TANBAN_BOARDS must be a non-empty JSON object")

    boards: dict[str, TanbanBoardConfig] = {}
    for public_id_raw, entry in data.items():
        public_id = normalize_public_id(str(public_id_raw))
        if not public_id:
            raise TanbanBoardsConfigError("TANBAN_BOARDS entries need a non-empty public_id key")
        if not isinstance(entry, dict):
            raise TanbanBoardsConfigError(f"TANBAN_BOARDS[{public_id_raw!r}] must be an object")
        board_id = entry.get("board_id")
        if not isinstance(board_id, int) or isinstance(board_id, bool) or board_id < 1:
            raise TanbanBoardsConfigError(
                f"TANBAN_BOARDS[{public_id_raw!r}].board_id must be a positive integer"
            )
        api_key = str(entry.get("api_key") or "").strip()
        webhook_secret = str(entry.get("webhook_secret") or "").strip()
        if public_id in boards:
            raise TanbanBoardsConfigError(f"duplicate board public_id in TANBAN_BOARDS: {public_id_raw}")
        boards[public_id] = TanbanBoardConfig(
            public_id=public_id,
            board_id=board_id,
            api_key=api_key,
            webhook_secret=webhook_secret,
        )
    return boards


def boards_from_legacy(
    *,
    board_id: int | None,
    api_key: str,
    webhook_secret: str,
    board_public_id: str | None,
) -> dict[str, TanbanBoardConfig]:
    """Build a one-board map from legacy single-board env vars.

    When ``board_public_id`` is unset, returns an empty map; callers keep using
    the legacy catch-all binding instead.
    """
    if board_id is None or not board_public_id:
        return {}
    public_id = normalize_public_id(board_public_id)
    if not public_id:
        return {}
    return {
        public_id: TanbanBoardConfig(
            public_id=public_id,
            board_id=board_id,
            api_key=api_key.strip(),
            webhook_secret=webhook_secret.strip(),
        )
    }


@dataclass(frozen=True)
class LegacyBoardBinding:
    """Single-board fallback when ``TANBAN_BOARDS`` / public_id map is unused."""

    board_id: int | None
    api_key: str
    webhook_secret: str


def board_public_id_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    board = payload.get("board")
    if not isinstance(board, dict):
        return None
    return normalize_public_id(board.get("public_id"))


def board_public_id_from_body(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return board_public_id_from_payload(payload if isinstance(payload, dict) else None)


def resolve_board(
    boards: dict[str, TanbanBoardConfig],
    legacy: LegacyBoardBinding | None,
    board_public_id: str | None,
) -> TanbanBoardConfig | LegacyBoardBinding | None:
    """Pick credentials for a webhook board public_id."""
    key = normalize_public_id(board_public_id)
    if key and key in boards:
        return boards[key]
    if legacy is not None and not boards:
        return legacy
    return None
