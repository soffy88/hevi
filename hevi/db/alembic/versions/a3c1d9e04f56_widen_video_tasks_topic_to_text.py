"""widen_video_tasks_topic_to_text

Revision ID: a3c1d9e04f56
Revises: f1a2b3c4d5e6
Create Date: 2026-07-11 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c1d9e04f56"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SPEC-001 短剧通道:episode_brief() 把一集的节拍/角色/事件摘要/原文对白降维成一段
    # topic 文本喂给现有 Director,常年超 255 字符,String(255) 会在 dispatch_season →
    # create_episode 时报 StringDataRightTruncationError。
    op.alter_column("video_tasks", "topic", type_=sa.Text(), existing_type=sa.String(255))


def downgrade() -> None:
    op.alter_column("video_tasks", "topic", type_=sa.String(255), existing_type=sa.Text())
