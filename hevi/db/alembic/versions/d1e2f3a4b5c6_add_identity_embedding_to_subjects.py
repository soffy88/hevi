"""add identity_embedding to subjects

3O manifest §C1:Subject 增身份/视觉向量列(CLIP L2-归一化,建角色时离线算)。
nullable —— 老数据/无参考图/算失败时为空,不阻断建角色;L3 审片以此为身份锚。

Revision ID: d1e2f3a4b5c6
Revises: b7e2c9a10f34
Create Date: 2026-07-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "b7e2c9a10f34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column(
            "identity_embedding",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subjects", "identity_embedding")
