"""Add title for operator run status display.

Revision ID: 0004_run_title
Revises: 0003_content_hash
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_run_title"
down_revision: Union[str, None] = "0003_content_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cursor_agent_runs") as batch:
        batch.add_column(sa.Column("title", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cursor_agent_runs") as batch:
        batch.drop_column("title")
