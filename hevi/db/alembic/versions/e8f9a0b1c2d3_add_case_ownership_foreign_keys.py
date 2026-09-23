"""Add database ownership and asset-reference constraints for VideoCase."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "video_cases",
        "user_id",
        existing_type=sa.String(length=255),
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="user_id::uuid",
    )
    op.create_foreign_key(
        "fk_video_cases_user",
        "video_cases",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_video_cases_original_asset",
        "video_cases",
        "assets",
        ["original_video_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_video_cases_thumbnail_asset",
        "video_cases",
        "assets",
        ["thumbnail_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_video_cases_thumbnail_asset", "video_cases", type_="foreignkey")
    op.drop_constraint("fk_video_cases_original_asset", "video_cases", type_="foreignkey")
    op.drop_constraint("fk_video_cases_user", "video_cases", type_="foreignkey")
    op.alter_column(
        "video_cases",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=255),
        postgresql_using="user_id::text",
    )
