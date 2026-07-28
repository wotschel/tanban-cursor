"""Query helpers for Cursor agent run status."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models import CursorAgentRun

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


def clamp_limit(limit: int | None) -> int:
    if limit is None or limit < 1:
        return DEFAULT_LIST_LIMIT
    return min(limit, MAX_LIST_LIMIT)


def list_runs(db: Session, *, limit: int | None = None) -> list[CursorAgentRun]:
    capped = clamp_limit(limit)
    return (
        db.query(CursorAgentRun)
        .order_by(CursorAgentRun.id.desc())
        .limit(capped)
        .all()
    )


def get_run(db: Session, run_id: int) -> CursorAgentRun | None:
    return db.query(CursorAgentRun).filter(CursorAgentRun.id == run_id).first()
