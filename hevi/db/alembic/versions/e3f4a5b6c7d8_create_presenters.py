"""create reusable digital-human presenter profiles"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3f4a5b6c7d8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "presenters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=True),
        sa.Column("voice_profile_id", sa.String(255), nullable=True),
        sa.Column("performance", sa.String(32), nullable=False, server_default="narrator"),
        sa.Column("motion", sa.String(32), nullable=False, server_default="picture_in_picture"),
        sa.Column("lipsync", sa.String(32), nullable=False, server_default="none"),
        sa.Column("delivery_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_presenters_user_id", "presenters", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_presenters_user_id", table_name="presenters")
    op.drop_table("presenters")
