"""persist licensed material-search provenance"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("preview_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("license_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "provider", "external_id", name="uq_stock_assets_user_provider_external"),
    )
    op.create_index("ix_stock_assets_user_created", "stock_assets", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_stock_assets_user_created", table_name="stock_assets")
    op.drop_table("stock_assets")
