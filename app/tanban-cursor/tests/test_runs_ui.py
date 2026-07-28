"""Operator runs status UI / API auth and listing."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

import deps
from database import get_db as real_get_db
from deps import require_status_ui_token
from main import app
from services.runs import clamp_limit, list_runs


def _patch_ui_token(monkeypatch, token: str = "ui-secret") -> None:
    mock_settings = MagicMock()
    mock_settings.status_ui_access_token.return_value = token
    monkeypatch.setattr(deps, "settings", mock_settings)


def test_clamp_limit_defaults_and_caps():
    assert clamp_limit(None) == 50
    assert clamp_limit(0) == 50
    assert clamp_limit(10) == 10
    assert clamp_limit(999) == 200


def test_list_runs_orders_desc_and_limits():
    db = MagicMock()
    query = db.query.return_value
    ordered = query.order_by.return_value
    ordered.limit.return_value.all.return_value = ["a", "b"]

    rows = list_runs(db, limit=5)

    assert rows == ["a", "b"]
    ordered.limit.assert_called_once_with(5)


def test_require_status_ui_token_accepts_query(monkeypatch):
    _patch_ui_token(monkeypatch)
    assert require_status_ui_token(token="ui-secret") == "ui-secret"


def test_require_status_ui_token_accepts_bearer(monkeypatch):
    _patch_ui_token(monkeypatch)
    assert require_status_ui_token(token=None, authorization="Bearer ui-secret") == "ui-secret"


def test_require_status_ui_token_rejects_wrong(monkeypatch):
    _patch_ui_token(monkeypatch)
    try:
        require_status_ui_token(token="nope")
        assert False, "expected HTTPException"
    except HTTPException as error:
        assert error.status_code == 401


def _sample_run(**overrides):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    data = {
        "id": 7,
        "board_public_id": "board-1",
        "card_public_id": "card-1",
        "title": "Ship it",
        "mode": "c-ask",
        "cursor_agent_id": "agent-1",
        "cursor_run_id": "run-1",
        "status": "finished",
        "error": None,
        "source_delivery_id": "del-1",
        "content_hash": "abc",
        "prompt": "Hello",
        "result_text": "World",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_runs_html_requires_token():
    client = TestClient(app)
    response = client.get("/runs")
    assert response.status_code == 401


def test_runs_html_lists_rows(monkeypatch):
    _patch_ui_token(monkeypatch)
    monkeypatch.setattr(
        "routers.runs.runs_service.list_runs",
        lambda _db, limit=50: [_sample_run()],
    )
    app.dependency_overrides[real_get_db] = lambda: MagicMock()
    try:
        client = TestClient(app)
        response = client.get("/runs", params={"token": "ui-secret"})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Cursor agent runs" in response.text
        assert "finished" in response.text
        assert "Ship it" in response.text
        assert "Card UUID" in response.text
        assert "card-1" in response.text
        assert "/runs/7?token=ui-secret" in response.text
    finally:
        app.dependency_overrides.clear()


def test_api_runs_json(monkeypatch):
    _patch_ui_token(monkeypatch)
    monkeypatch.setattr(
        "routers.runs.runs_service.list_runs",
        lambda _db, limit=50: [_sample_run()],
    )
    app.dependency_overrides[real_get_db] = lambda: MagicMock()
    try:
        client = TestClient(app)
        response = client.get("/api/runs", headers={"X-Status-UI-Token": "ui-secret"})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["runs"][0]["id"] == 7
        assert body["runs"][0]["title"] == "Ship it"
        assert body["runs"][0]["card_public_id"] == "card-1"
        assert body["runs"][0]["mode"] == "c-ask"
        assert body["runs"][0]["status"] == "finished"
    finally:
        app.dependency_overrides.clear()


def test_run_detail_html_shows_title_and_uuids(monkeypatch):
    _patch_ui_token(monkeypatch)
    monkeypatch.setattr(
        "routers.runs.runs_service.get_run",
        lambda _db, _run_id: _sample_run(),
    )
    app.dependency_overrides[real_get_db] = lambda: MagicMock()
    try:
        client = TestClient(app)
        response = client.get("/runs/7", params={"token": "ui-secret"})
        assert response.status_code == 200
        assert "Ship it" in response.text
        assert "Run #7" in response.text
        assert "Card UUID" in response.text
        assert "Board UUID" in response.text
        assert "card-1" in response.text
        assert "board-1" in response.text
    finally:
        app.dependency_overrides.clear()


def test_run_detail_not_found(monkeypatch):
    _patch_ui_token(monkeypatch)
    monkeypatch.setattr(
        "routers.runs.runs_service.get_run",
        lambda _db, _run_id: None,
    )
    app.dependency_overrides[real_get_db] = lambda: MagicMock()
    try:
        client = TestClient(app)
        response = client.get("/api/runs/99", params={"token": "ui-secret"})
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
