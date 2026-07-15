"""add reference_roles to subjects

设计文档 §5.2:参考素材的正交角色标签(身份锚点 / 构图氛围参考等),跟 subject_type
(character/portrait/product/scene)是两个独立维度。keyed by reference_images 里的
路径,value 自由文本(不强制枚举)。nullable,不影响任何现有 reference_images 消费方。

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-07-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column(
            "reference_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subjects", "reference_roles")
