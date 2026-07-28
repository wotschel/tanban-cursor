"""HTTP client for the TanBan board API (Bearer board API key)."""

from __future__ import annotations

from typing import Any

import httpx

from config import settings


class TanbanClientError(RuntimeError):
    pass


class TanbanClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.tanban_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.tanban_api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise TanbanClientError("TANBAN_API_KEY is not configured")
        if not self.base_url:
            raise TanbanClientError("TANBAN_BASE_URL is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, *, json: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json=json)

    def patch(self, path: str, *, json: dict[str, Any] | None = None) -> Any:
        return self._request("PATCH", path, json=json)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=self._headers(), params=params, json=json)
        except httpx.HTTPError as error:
            raise TanbanClientError(f"TanBan request failed: {error}") from error
        if response.status_code >= 400:
            detail = response.text[:300]
            raise TanbanClientError(f"TanBan {method} {path} -> {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get_card(self, card_id: int) -> Any:
        return self.get(f"/api/cards/{card_id}")

    def list_cards(self, board_id: int) -> list[Any]:
        result = self.get("/api/cards", params={"board_id": board_id})
        return result if isinstance(result, list) else []

    def find_card_by_public_id(self, board_id: int, public_id: str) -> dict[str, Any] | None:
        target = str(public_id).casefold()
        for card in self.list_cards(board_id):
            if not isinstance(card, dict):
                continue
            if str(card.get("public_id") or "").casefold() == target:
                return card
        return None

    def add_comment(self, card_id: int, text: str) -> Any:
        return self.post(f"/api/cards/{card_id}/comments", json={"text": text})

    def set_card_blocked(self, card_id: int, *, reason: str) -> Any:
        return self.patch(
            f"/api/cards/{card_id}",
            json={"blocked": True, "blocked_reason": reason},
        )
