"""Add content_hash for unchanged card re-dispatch skip.

Revision ID: 0003_content_hash
Revises: 0002_agent_mode
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_content_hash"
down_revision: Union[str, None] = "0002_agent_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cursor_agent_runs") as batch:
        batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch.create_index("ix_cursor_agent_runs_content_hash", ["content_hash"])


def downgrade() -> None:
    with op.batch_alter_table("cursor_agent_runs") as batch:
        batch.drop_index("ix_cursor_agent_runs_content_hash")
        batch.drop_column("content_hash")
