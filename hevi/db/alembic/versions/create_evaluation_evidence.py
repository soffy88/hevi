"""create evaluation_evidence table

P0-B: Artifact-level constraint evaluation evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b7"
down_revision: str | None = "c0d1e2f3a4b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_evidence",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("artifact_id", sa.UUID(), nullable=False),
        sa.Column("constraint_id", sa.Text(), nullable=True),
        sa.Column("evaluator_id", sa.Text(), nullable=False),
        sa.Column("evaluator_version", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),  # NULL = UNKNOWN
        sa.Column("evidence_artifact_ids", sa.JSON(), nullable=False, default=list),
        sa.Column("details", sa.JSON(), nullable=False, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_attempt", "evaluation_evidence", ["attempt_id"])
    op.create_index("ix_eval_constraint", "evaluation_evidence", ["constraint_id"])
    op.create_index("ix_eval_artifact", "evaluation_evidence", ["artifact_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_artifact", table_name="evaluation_evidence")
    op.drop_index("ix_eval_constraint", table_name="evaluation_evidence")
    op.drop_index("ix_eval_attempt", table_name="evaluation_evidence")
    op.drop_table("evaluation_evidence")
