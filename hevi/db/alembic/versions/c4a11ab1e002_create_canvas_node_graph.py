"""create canvas node/edge/artifact/revision/cost tables (canvas MVP)

The canvas graph currently lives only in ``canvas_graphs.nodes_json`` /
``edges_json``.  This migration adds the first-class node graph that the
execution engine, node revisions and per-node self-check need, while the JSON
blobs remain the frontend compatibility mirror (dual write).

Revision ID: c4a11ab1e002
Revises: c4a11ab1e001
Create Date: 2026-11-08 09:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4a11ab1e002"
down_revision: str | Sequence[str] | None = "c4a11ab1e001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "canvas_graphs",
        sa.Column("graph_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "canvas_graphs", sa.Column("materialized_at", sa.DateTime(), nullable=True)
    )

    op.create_table(
        "canvas_nodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("graph_id", sa.UUID(), nullable=False),
        sa.Column("node_key", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("sub_type", sa.String(length=64), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("config", _JSONB, nullable=False, server_default="{}"),
        sa.Column("input_refs", _JSONB, nullable=False, server_default="[]"),
        sa.Column("position", _JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("review", _JSONB, nullable=True),
        sa.Column("output", _JSONB, nullable=True),
        sa.Column(
            "estimated_cost", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column("actual_cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["graph_id"], ["canvas_graphs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_id", "node_key", name="uq_canvas_nodes_graph_key"),
    )
    op.create_index("ix_canvas_nodes_graph_id", "canvas_nodes", ["graph_id"])
    op.create_index("ix_canvas_nodes_status", "canvas_nodes", ["status"])

    op.create_table(
        "canvas_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("graph_id", sa.UUID(), nullable=False),
        sa.Column("edge_key", sa.String(length=255), nullable=False),
        sa.Column("from_node_id", sa.UUID(), nullable=False),
        sa.Column("to_node_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="data"),
        sa.Column("meta", _JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["graph_id"], ["canvas_graphs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_node_id"], ["canvas_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_node_id"], ["canvas_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("graph_id", "edge_key", name="uq_canvas_edges_graph_key"),
    )
    op.create_index("ix_canvas_edges_graph_id", "canvas_edges", ["graph_id"])
    op.create_index("ix_canvas_edges_from", "canvas_edges", ["from_node_id"])
    op.create_index("ix_canvas_edges_to", "canvas_edges", ["to_node_id"])

    op.create_table(
        "canvas_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("graph_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("digest", sa.String(length=128), nullable=True),
        sa.Column("mime", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("meta", _JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["graph_id"], ["canvas_graphs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["canvas_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canvas_artifacts_node_id", "canvas_artifacts", ["node_id"])
    op.create_index("ix_canvas_artifacts_graph_id", "canvas_artifacts", ["graph_id"])
    op.create_index("ix_canvas_artifacts_digest", "canvas_artifacts", ["digest"])

    op.create_table(
        "canvas_node_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config_snapshot", _JSONB, nullable=False, server_default="{}"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("review_result", _JSONB, nullable=True),
        sa.Column("output", _JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["canvas_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", "revision", name="uq_canvas_revisions_node_rev"),
    )
    op.create_index("ix_canvas_revisions_node_id", "canvas_node_revisions", ["node_id"])

    op.create_table(
        "canvas_node_costs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("estimate", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("actual", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("pricing_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["canvas_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canvas_node_costs_node_id", "canvas_node_costs", ["node_id"])


def downgrade() -> None:
    op.drop_index("ix_canvas_node_costs_node_id", table_name="canvas_node_costs")
    op.drop_table("canvas_node_costs")
    op.drop_index("ix_canvas_revisions_node_id", table_name="canvas_node_revisions")
    op.drop_table("canvas_node_revisions")
    op.drop_index("ix_canvas_artifacts_digest", table_name="canvas_artifacts")
    op.drop_index("ix_canvas_artifacts_graph_id", table_name="canvas_artifacts")
    op.drop_index("ix_canvas_artifacts_node_id", table_name="canvas_artifacts")
    op.drop_table("canvas_artifacts")
    op.drop_index("ix_canvas_edges_to", table_name="canvas_edges")
    op.drop_index("ix_canvas_edges_from", table_name="canvas_edges")
    op.drop_index("ix_canvas_edges_graph_id", table_name="canvas_edges")
    op.drop_table("canvas_edges")
    op.drop_index("ix_canvas_nodes_status", table_name="canvas_nodes")
    op.drop_index("ix_canvas_nodes_graph_id", table_name="canvas_nodes")
    op.drop_table("canvas_nodes")
    op.drop_column("canvas_graphs", "materialized_at")
    op.drop_column("canvas_graphs", "graph_revision")
