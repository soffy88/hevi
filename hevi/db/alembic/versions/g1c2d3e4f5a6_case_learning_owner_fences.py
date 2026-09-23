"""Add database-enforced owner fences to intelligence evidence projections."""

from collections.abc import Sequence

from alembic import op

revision: str = "g1c2d3e4f5a6"
down_revision: str | None = "g0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_video_patterns_id_user", "video_patterns", ["id", "user_id"])
    op.create_unique_constraint("uq_case_reproductions_id_user", "case_reproductions", ["id", "user_id"])
    op.create_foreign_key(
        "fk_pattern_evidence_pattern_owner", "video_pattern_evidence", "video_patterns",
        ["pattern_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_pattern_evidence_case_owner", "video_pattern_evidence", "video_cases",
        ["case_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_pattern_evidence_reproduction_owner", "video_pattern_evidence", "case_reproductions",
        ["reproduction_id", "user_id"], ["id", "user_id"], ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_pattern_evidence_reproduction_owner", "video_pattern_evidence", type_="foreignkey")
    op.drop_constraint("fk_pattern_evidence_case_owner", "video_pattern_evidence", type_="foreignkey")
    op.drop_constraint("fk_pattern_evidence_pattern_owner", "video_pattern_evidence", type_="foreignkey")
    op.drop_constraint("uq_case_reproductions_id_user", "case_reproductions", type_="unique")
    op.drop_constraint("uq_video_patterns_id_user", "video_patterns", type_="unique")
