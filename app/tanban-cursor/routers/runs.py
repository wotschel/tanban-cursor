"""Operator status UI and JSON for Cursor agent runs."""

from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

import schemas
from database import get_db
from deps import require_status_ui_token
from services import runs as runs_service

router = APIRouter(tags=["runs"])


def _fmt_dt(value: object | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(value)


def _esc(value: object | None) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value), quote=True)


def _status_class(status: str) -> str:
    normalized = (status or "").strip().casefold()
    if normalized in {"finished", "completed", "success"}:
        return "ok"
    if normalized in {"error", "failed"}:
        return "err"
    if normalized in {"running", "creating", "pending"}:
        return "active"
    if normalized == "skipped":
        return "muted"
    return "muted"


def _token_query(token: str) -> str:
    return urlencode({"token": token})


def _page(title: str, body: str, *, refresh_seconds: int | None = None) -> HTMLResponse:
    refresh = (
        f'<meta http-equiv="refresh" content="{refresh_seconds}">'
        if refresh_seconds and refresh_seconds > 0
        else ""
    )
    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh}
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #0f1419;
      --panel: #1a222c;
      --text: #e7ecf1;
      --muted: #8b98a5;
      --line: #2a3541;
      --ok: #3d9a6a;
      --err: #c45c5c;
      --active: #c9a227;
      --link: #7eb8da;
      --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 14px/1.45 var(--sans);
      color: var(--text);
      background:
        radial-gradient(1200px 600px at 10% -10%, #1c2a38 0%, transparent 55%),
        var(--bg);
      min-height: 100vh;
    }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 28px 20px 48px; }}
    h1 {{ font-size: 1.45rem; font-weight: 600; margin: 0 0 6px; letter-spacing: -0.02em; }}
    .sub {{ color: var(--muted); margin: 0 0 22px; }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    th, td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
      font-weight: 600;
    }}
    tr:last-child td {{ border-bottom: none; }}
    .mono {{ font-family: var(--mono); font-size: 0.85rem; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border: 1px solid var(--line);
      font-family: var(--mono);
      font-size: 0.78rem;
    }}
    .badge.ok {{ color: var(--ok); border-color: var(--ok); }}
    .badge.err {{ color: var(--err); border-color: var(--err); }}
    .badge.active {{ color: var(--active); border-color: var(--active); }}
    .badge.muted {{ color: var(--muted); }}
    .empty {{ color: var(--muted); padding: 24px; background: var(--panel); border: 1px solid var(--line); }}
    .meta {{ display: grid; grid-template-columns: 140px 1fr; gap: 8px 16px; margin: 18px 0; }}
    .meta dt {{ color: var(--muted); }}
    .meta dd {{ margin: 0; word-break: break-word; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 14px;
      font-family: var(--mono);
      font-size: 0.82rem;
      max-height: 420px;
      overflow: auto;
    }}
    .nav {{ margin-bottom: 18px; color: var(--muted); }}
  </style>
</head>
<body>
  <main>
    {body}
  </main>
</body>
</html>
"""
    return HTMLResponse(document)


def _run_to_out(row) -> schemas.CursorAgentRunOut:
    return schemas.CursorAgentRunOut(
        id=row.id,
        board_public_id=row.board_public_id,
        card_public_id=row.card_public_id,
        title=row.title,
        mode=row.mode,
        cursor_agent_id=row.cursor_agent_id,
        cursor_run_id=row.cursor_run_id,
        status=row.status,
        error=row.error,
        source_delivery_id=row.source_delivery_id,
        created_at=row.created_at if isinstance(row.created_at, datetime) else None,
        updated_at=row.updated_at if isinstance(row.updated_at, datetime) else None,
    )


def _run_to_detail(row) -> schemas.CursorAgentRunDetailOut:
    base = _run_to_out(row)
    return schemas.CursorAgentRunDetailOut(
        **base.model_dump(),
        prompt=row.prompt,
        result_text=row.result_text,
        content_hash=row.content_hash,
    )


@router.get("/runs", response_class=HTMLResponse)
def runs_page(
    db: Session = Depends(get_db),
    token: str = Depends(require_status_ui_token),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = runs_service.list_runs(db, limit=limit)
    q = _token_query(token)
    if not rows:
        body = f"""
        <div class="nav"><a href="/runs?{q}">Runs</a> · <a href="/api/runs?{q}">JSON</a></div>
        <h1>Cursor agent runs</h1>
        <p class="sub">Auto-refresh every 15s · limit={limit}</p>
        <div class="empty">No runs yet.</div>
        """
        return _page("tanban-cursor runs", body, refresh_seconds=15)

    cells = []
    for row in rows:
        cells.append(
            f"""<tr>
              <td class="mono"><a href="/runs/{row.id}?{q}">{row.id}</a></td>
              <td>{_esc(row.title)}</td>
              <td><span class="badge {_status_class(row.status)}">{_esc(row.status)}</span></td>
              <td class="mono">{_esc(row.mode)}</td>
              <td class="mono">{_esc(row.card_public_id)}</td>
              <td class="mono">{_esc(row.cursor_agent_id)}</td>
              <td class="mono">{_esc(_fmt_dt(row.updated_at))}</td>
              <td>{_esc((row.error or "")[:120] or None)}</td>
            </tr>"""
        )
    body = f"""
    <div class="nav"><a href="/runs?{q}">Runs</a> · <a href="/api/runs?{q}">JSON</a></div>
    <h1>Cursor agent runs</h1>
    <p class="sub">Auto-refresh every 15s · showing {len(rows)} (limit={limit})</p>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Title</th><th>Status</th><th>Mode</th><th>Card UUID</th>
          <th>Agent</th><th>Updated</th><th>Error</th>
        </tr>
      </thead>
      <tbody>
        {"".join(cells)}
      </tbody>
    </table>
    """
    return _page("tanban-cursor runs", body, refresh_seconds=15)


@router.get("/api/runs")
def runs_json(
    db: Session = Depends(get_db),
    _token: str = Depends(require_status_ui_token),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows = runs_service.list_runs(db, limit=limit)
    payload = [_run_to_out(row).model_dump(mode="json") for row in rows]
    return JSONResponse({"runs": payload, "count": len(payload)})


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail_page(
    run_id: int,
    db: Session = Depends(get_db),
    token: str = Depends(require_status_ui_token),
):
    row = runs_service.get_run(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    q = _token_query(token)
    heading = (row.title or "").strip() or f"Run #{row.id}"
    body = f"""
    <div class="nav"><a href="/runs?{q}">← Runs</a> · <a href="/api/runs/{run_id}?{q}">JSON</a></div>
    <h1>{_esc(heading)}</h1>
    <p class="sub">Run #{row.id} · <span class="badge {_status_class(row.status)}">{_esc(row.status)}</span>
      · mode {_esc(row.mode)}</p>
    <dl class="meta">
      <dt>Title</dt><dd>{_esc(row.title)}</dd>
      <dt>Board UUID</dt><dd class="mono">{_esc(row.board_public_id)}</dd>
      <dt>Card UUID</dt><dd class="mono">{_esc(row.card_public_id)}</dd>
      <dt>Agent</dt><dd class="mono">{_esc(row.cursor_agent_id)}</dd>
      <dt>Cursor run</dt><dd class="mono">{_esc(row.cursor_run_id)}</dd>
      <dt>Delivery</dt><dd class="mono">{_esc(row.source_delivery_id)}</dd>
      <dt>Content hash</dt><dd class="mono">{_esc(row.content_hash)}</dd>
      <dt>Created</dt><dd class="mono">{_esc(_fmt_dt(row.created_at))}</dd>
      <dt>Updated</dt><dd class="mono">{_esc(_fmt_dt(row.updated_at))}</dd>
      <dt>Error</dt><dd>{_esc(row.error)}</dd>
    </dl>
    <h2>Prompt</h2>
    <pre>{html.escape(row.prompt or "(empty)")}</pre>
    <h2>Result</h2>
    <pre>{html.escape(row.result_text or "(empty)")}</pre>
    """
    return _page(f"tanban-cursor run #{row.id}", body)


@router.get("/api/runs/{run_id}")
def run_detail_json(
    run_id: int,
    db: Session = Depends(get_db),
    _token: str = Depends(require_status_ui_token),
):
    row = runs_service.get_run(db, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return JSONResponse(_run_to_detail(row).model_dump(mode="json"))
