"""Persist compiled execution plans and DAG nodes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8c9d0e1f234"
down_revision: str | None = "ae1f2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("execution_plans"):
        op.create_table(
            "execution_plans",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "production_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("productions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "revision_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("production_revisions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(32), nullable=False, server_default="compiled"),
            sa.Column("plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("production_id", "revision_id", "plan_version", name="uq_execution_plan_revision"),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_execution_plans_production_id "
        "ON execution_plans (production_id)"
    )
    if not inspector.has_table("execution_nodes"):
        op.create_table(
            "execution_nodes",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "plan_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("execution_plans.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("node_key", sa.String(255), nullable=False),
            sa.Column("op_type", sa.String(128), nullable=False),
            sa.Column("capability", sa.String(128), nullable=False),
            sa.Column("requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
            sa.Column("dependencies", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
            sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
            sa.UniqueConstraint("plan_id", "node_key", name="uq_execution_node_key"),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_execution_nodes_plan_id "
        "ON execution_nodes (plan_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_execution_nodes_plan_id", table_name="execution_nodes")
    op.drop_table("execution_nodes")
    op.drop_index("ix_execution_plans_production_id", table_name="execution_plans")
    op.drop_table("execution_plans")
