"""Add per-consumer event offsets, DLQ state and relational constraints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c93d4e5f607"
down_revision: str | None = "7b8293a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_consumer_offsets",
        sa.Column("consumer_name", sa.String(128), primary_key=True),
        sa.Column("last_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "event_dead_letters",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("domain_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "production_constraints",
        sa.Column("id", sa.String(128), nullable=False),
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
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("compile_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verification_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fallback_policy", sa.String(16), nullable=False, server_default="fail"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("revision_id", "id"),
    )
    op.create_index(
        "ix_production_constraints_revision_type",
        "production_constraints",
        ["revision_id", "type"],
    )
    op.create_table(
        "constraint_dependencies",
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "constraint_id",
            sa.String(128),
            nullable=False,
        ),
        sa.Column(
            "depends_on_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "depends_on_id",
            sa.String(128),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "revision_id", "constraint_id", "depends_on_revision_id", "depends_on_id"
        ),
    )
    op.create_table(
        "constraint_coverage",
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_revisions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("expected_fields", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("derived_constraints", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compiled_constraints", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_constraints", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_constraints", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unsupported_constraints", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("silent_drops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("constraint_coverage")
    op.drop_table("constraint_dependencies")
    op.drop_index("ix_production_constraints_revision_type", table_name="production_constraints")
    op.drop_table("production_constraints")
    op.drop_table("event_dead_letters")
    op.drop_table("event_consumer_offsets")
