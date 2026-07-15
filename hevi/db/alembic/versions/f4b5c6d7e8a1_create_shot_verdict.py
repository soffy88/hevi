"""create shot_verdict

HEVI-ARCHITECTURE v3.2 §6.2:成片逐镜头裁决结果持久化——护城河②(verdict 数据资产)
的地基。每个镜头一次裁决一行:黑帧/hand safety/身份一致等检查结果 + 诊断分类 +
retake 五档决策(§4.1.2)。checks_json 留给未来挂载树逐节点(衣/发/声/光/道具,§6.1.0)
扩展,不必每加一类检查就改表结构。数据无法补录,越早存越好。

Revision ID: f4b5c6d7e8a1
Revises: a3c1d9e04f56
Create Date: 2026-07-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4b5c6d7e8a1"
down_revision: str | None = "a3c1d9e04f56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shot_verdict",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("video_tasks.id"),
            nullable=False,
        ),
        sa.Column("shot_index", sa.Integer(), nullable=False),
        sa.Column("shot_id", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        # 身份一致:tongjian 渲染已算的 character_consistency(CLIP,越大越像;None=没算)
        sa.Column("identity_score", sa.Float(), nullable=True),
        # 黑帧占比:0=全好,1=全黑(采样帧里黑帧比例)
        sa.Column("black_ratio", sa.Float(), nullable=True),
        sa.Column("hand_safety_ok", sa.Boolean(), nullable=True),
        # 检查明细(可扩展:black/hand/identity + 未来挂载树节点)
        sa.Column("checks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # 诊断分类(editor.py 固定分类表)+ retake 五档(keep/fix_in_post/edit/re_roll/rewrite)
        sa.Column("diagnosis_category", sa.String(64), nullable=True),
        sa.Column("retake_tier", sa.String(32), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_shot_verdict_task_id", "shot_verdict", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_shot_verdict_task_id", table_name="shot_verdict")
    op.drop_table("shot_verdict")
