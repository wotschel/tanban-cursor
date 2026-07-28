#!/usr/bin/env python3
"""CLI helpers for the tanban-cursor bridge."""

from __future__ import annotations

import argparse
import sys

from config import settings
from database import SessionLocal
from models import CursorAgentRun, InboundWebhookEvent


def cmd_help(_args: argparse.Namespace) -> int:
    print(
        """Commands:
  help              Show this help
  health            Print local health summary
  webhook-list      List recent inbound TanBan webhook events
  run-list          List Cursor agent run records
"""
    )
    return 0


def cmd_health(_args: argparse.Namespace) -> int:
    print(f"app_env={settings.app_env}")
    print(f"tanban_base_url={settings.tanban_base_url or '(unset)'}")
    print(f"tanban_boards={len(settings.tanban_boards)}")
    for public_id, board in sorted(settings.tanban_boards.items()):
        print(
            f"  board public_id={public_id} board_id={board.board_id} "
            f"api_key={'set' if board.api_key else 'unset'} "
            f"webhook_secret={'set' if board.webhook_secret else 'unset'}"
        )
    if settings.tanban_legacy is not None:
        legacy = settings.tanban_legacy
        print(
            f"tanban_legacy board_id={legacy.board_id or '(unset)'} "
            f"api_key={'set' if legacy.api_key else 'unset'} "
            f"webhook_secret={'set' if legacy.webhook_secret else 'unset'}"
        )
    print(f"cursor_active={settings.cursor_active}")
    print(f"cursor_api_key={'set' if settings.cursor_api_key else 'unset'}")
    print(f"cursor_model={settings.cursor_model}")
    print(f"cursor_runtime={settings.cursor_runtime}")
    print(f"cursor_repository={settings.cursor_repository or '(unset)'}")
    print(f"status_ui_token={'set' if settings.status_ui_token else 'unset (uses SECRET_KEY)'}")
    return 0


def cmd_webhook_list(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(InboundWebhookEvent)
            .order_by(InboundWebhookEvent.id.desc())
            .limit(args.limit)
            .all()
        )
        if not rows:
            print("(no inbound webhook events)")
            return 0
        for row in rows:
            print(
                f"{row.id}\t{row.delivery_id}\t{row.event}\t"
                f"board={row.board_public_id or '-'}\tobject={row.object_public_id or '-'}\t"
                f"processed={row.processed}"
            )
    finally:
        db.close()
    return 0


def cmd_run_list(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        rows = db.query(CursorAgentRun).order_by(CursorAgentRun.id.desc()).limit(args.limit).all()
        if not rows:
            print("(no cursor agent runs)")
            return 0
        for row in rows:
            title = (row.title or "").replace("\t", " ").strip() or "-"
            print(
                f"{row.id}\t{row.status}\tmode={row.mode or '-'}\t"
                f"card={row.card_public_id or '-'}\ttitle={title}\t"
                f"agent={row.cursor_agent_id or '-'}\trun={row.cursor_run_id or '-'}"
            )
    finally:
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage.py", description="tanban-cursor management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("help", help="Show command list")

    sub.add_parser("health", help="Print configuration health summary")

    webhook_list = sub.add_parser("webhook-list", help="List inbound webhook events")
    webhook_list.add_argument("--limit", type=int, default=20)

    run_list = sub.add_parser("run-list", help="List Cursor agent run records")
    run_list.add_argument("--limit", type=int, default=20)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "help": cmd_help,
        "health": cmd_health,
        "webhook-list": cmd_webhook_list,
        "run-list": cmd_run_list,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
