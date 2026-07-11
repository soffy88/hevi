"""add identity_embedding_face to subjects

HEVI 路线图 Phase2 #34:多区域 identity embedding。identity_embedding(全图,不裁剪)
之外新增脸部区域向量(kind="face",几何裁剪启发式,见 subject_embed.py 顶部注释)。
两个区域分开存,审片时各比一次取更像的那个——不是真人脸检测,只是常见半身像构图
的裁剪,背影/侧身镜头裁不到脸时可以靠全图向量兜底。nullable,同 identity_embedding。

Revision ID: e7f8a9b0c1d2
Revises: b5c6d7e8f9a0
Create Date: 2026-07-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column(
            "identity_embedding_face",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subjects", "identity_embedding_face")
