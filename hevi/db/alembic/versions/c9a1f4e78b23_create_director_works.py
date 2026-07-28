"""create director_works (persist locked pipeline artifacts)

P0(2026-07-23):导演管线的作品此前只活在 `director_pipeline._WORKS` 内存字典里,进程一死
concept/screenplay/design_list/world_bible/scene_script 全丢——批C 那次 $15.711 产集的 locked
scene_script 就是这么没的,导致 A/B 对照做不成。这张表把锁定产物落库,每次真实产集的输入可复现、
可对照。一行一个 work,五卷各存一个 JSONB。

Revision ID: c9a1f4e78b23
Revises: eaff3a92445c
Create Date: 2026-07-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9a1f4e78b23"
down_revision: str | None = "eaff3a92445c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "director_works",
        # work_id 是 director_pipeline 侧生成的字符串 id(不是 UUID 类型),沿用原样当主键
        sa.Column("work_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("locked_through", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column("visual_style", sa.String(length=32), nullable=False, server_default="realistic"),
        sa.Column("material_text", sa.Text(), nullable=False, server_default=""),
        # 五卷锁定产物,各存一个 JSONB(未生成到的阶段存 NULL)
        sa.Column("concept", _JSONB, nullable=True),
        sa.Column("screenplay", _JSONB, nullable=True),
        sa.Column("design_list", _JSONB, nullable=True),
        sa.Column("world_bible", _JSONB, nullable=True),
        sa.Column("scene_script", _JSONB, nullable=True),
        # 产集时回填:这个 work 产出了哪个 video_task(A/B 的关键连接——从成片反查确切输入)
        sa.Column("video_task_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("work_id"),
    )
    op.create_index("ix_director_works_user_id", "director_works", ["user_id"])
    op.create_index("ix_director_works_video_task_id", "director_works", ["video_task_id"])


def downgrade() -> None:
    op.drop_index("ix_director_works_video_task_id", table_name="director_works")
    op.drop_index("ix_director_works_user_id", table_name="director_works")
    op.drop_table("director_works")
