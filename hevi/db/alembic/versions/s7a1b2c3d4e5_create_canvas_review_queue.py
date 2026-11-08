"""create the canvas ChatGPT review queue

A node that finished execution and its deterministic offline self-check writes
one row here.  A remote reviewer (ChatGPT through the local2 MCP connector)
claims it, then submits a pass/fail verdict.  The queue is asynchronous by
design: it never blocks rendering.

Revision ID: s7a1b2c3d4e5
Revises: f6a7b8c9d0e1
Create Date: 2026-11-08 17:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "s7a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "canvas_review_queue",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("graph_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("sentence_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("thumbnails", _JSONB, nullable=False, server_default="[]"),
        sa.Column("offline_review", _JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("result", _JSONB, nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["graph_id"], ["canvas_graphs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canvas_review_queue_status", "canvas_review_queue", ["status"])
    op.create_index("ix_canvas_review_queue_expires", "canvas_review_queue", ["expires_at"])
    op.create_index(
        "ix_canvas_review_queue_graph_node", "canvas_review_queue", ["graph_id", "node_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_canvas_review_queue_graph_node", table_name="canvas_review_queue")
    op.drop_index("ix_canvas_review_queue_expires", table_name="canvas_review_queue")
    op.drop_index("ix_canvas_review_queue_status", table_name="canvas_review_queue")
    op.drop_table("canvas_review_queue")
