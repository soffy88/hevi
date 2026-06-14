"""create_canvas_graphs

Revision ID: c4f0b3d82e51
Revises: b3f0a2c91d45
Create Date: 2026-06-14 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4f0b3d82e51"
down_revision: str | None = "b3f0a2c91d45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canvas_graphs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default="Untitled"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "nodes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "edges_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canvas_graphs_user_id", "canvas_graphs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_canvas_graphs_user_id", table_name="canvas_graphs")
    op.drop_table("canvas_graphs")
