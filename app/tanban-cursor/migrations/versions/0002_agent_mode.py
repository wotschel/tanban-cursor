"""Add mode column and widen public_id fields for UUIDs.

Revision ID: 0002_agent_mode
Revises: 0001_initial
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_agent_mode"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cursor_agent_runs") as batch:
        batch.add_column(sa.Column("mode", sa.String(length=16), nullable=True))
        batch.create_index("ix_cursor_agent_runs_mode", ["mode"])
        batch.alter_column(
            "board_public_id",
            existing_type=sa.String(length=32),
            type_=sa.String(length=36),
            existing_nullable=True,
        )
        batch.alter_column(
            "card_public_id",
            existing_type=sa.String(length=32),
            type_=sa.String(length=36),
            existing_nullable=True,
        )

    with op.batch_alter_table("inbound_webhook_events") as batch:
        batch.alter_column(
            "board_public_id",
            existing_type=sa.String(length=32),
            type_=sa.String(length=36),
            existing_nullable=True,
        )
        batch.alter_column(
            "object_public_id",
            existing_type=sa.String(length=32),
            type_=sa.String(length=36),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("inbound_webhook_events") as batch:
        batch.alter_column(
            "object_public_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
        batch.alter_column(
            "board_public_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=32),
            existing_nullable=True,
        )

    with op.batch_alter_table("cursor_agent_runs") as batch:
        batch.alter_column(
            "card_public_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
        batch.alter_column(
            "board_public_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
        batch.drop_index("ix_cursor_agent_runs_mode")
        batch.drop_column("mode")
