"""Create canonical Video Intelligence case records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "8c9d0e1f2a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_platform", sa.String(128), nullable=True),
        sa.Column("source_author", sa.String(255), nullable=True),
        sa.Column("provenance_status", sa.String(32), nullable=False, server_default="unverified"),
        sa.Column("provenance_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("original_video_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("thumbnail_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_prompt", sa.Text(), nullable=True),
        sa.Column("prompt_origin", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("reference_assets_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("aspect_ratio", sa.String(32), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("declared_model", sa.String(255), nullable=True),
        sa.Column("declared_model_version", sa.String(128), nullable=True),
        sa.Column("rights_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("rights_metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("analysis_status", sa.String(32), nullable=False, server_default="not_started"),
        sa.Column("duplicate_outcome", sa.String(32), nullable=False, server_default="new"),
        sa.Column("exact_asset_sha256", sa.String(64), nullable=True),
        sa.Column("source_fingerprint", sa.String(512), nullable=True),
        sa.Column("shots_json", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_video_cases_user_created", "video_cases", ["user_id", "created_at"])
    op.create_index("ix_video_cases_user_hash", "video_cases", ["user_id", "exact_asset_sha256"])
    op.create_index(
        "uq_video_cases_user_idempotency",
        "video_cases",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_video_cases_user_idempotency", table_name="video_cases")
    op.drop_index("ix_video_cases_user_hash", table_name="video_cases")
    op.drop_index("ix_video_cases_user_created", table_name="video_cases")
    op.drop_table("video_cases")
