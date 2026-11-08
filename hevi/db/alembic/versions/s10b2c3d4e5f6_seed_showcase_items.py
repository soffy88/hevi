"""seed_showcase_items (home 官方精选 cold start)

The home gallery showed "该分区暂无示例作品" in production because
``showcase_items`` was never seeded.  Two official, non-commercial demo clips
(rendered by this project, AI label burned in) ship in the web image under
``/showcase``.  Inserts are idempotent so re-running is safe.

Revision ID: s10b2c3d4e5f6
Revises: s10a1b2c3d4e5
Create Date: 2026-11-09 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s10b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "s10a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ITEMS = (
    {
        "id": "official-collage-cat",
        "category": "short_video",
        "title": "海边橘猫 · 纸拼贴口播",
        "description": "30 秒 · 9:16 · 纸拼贴定格 + 中文旁白",
        "media_url": "/showcase/collage-cat.mp4",
        "thumbnail_url": "/showcase/collage-cat.jpg",
        "prompt": "海边的一只橘猫看着一层层海浪",
        "sort_order": 10,
    },
    {
        "id": "official-koubo-cat",
        "category": "avatar_narration",
        "title": "海边橘猫 · 口播精剪",
        "description": "30 秒 · 9:16 · 配音、字幕与头像口播",
        "media_url": "/showcase/koubo-cat.mp4",
        "thumbnail_url": "/showcase/koubo-cat.jpg",
        "prompt": "海边的一只橘猫趴在礁石上晒太阳",
        "sort_order": 20,
    },
)


def upgrade() -> None:
    for item in _ITEMS:
        op.execute(
            sa.text(
                "INSERT INTO showcase_items "
                "(id, category, title, description, media_url, thumbnail_url, prompt, "
                " gen_params, sort_order, is_active, created_at) "
                "VALUES (:id, :category, :title, :description, :media_url, :thumbnail_url, "
                " :prompt, CAST(:gen_params AS jsonb), :sort_order, true, now()) "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                id=item["id"],
                category=item["category"],
                title=item["title"],
                description=item["description"],
                media_url=item["media_url"],
                thumbnail_url=item["thumbnail_url"],
                prompt=item["prompt"],
                gen_params='{"official": true, "ai_label": "AI 生成"}',
                sort_order=item["sort_order"],
            )
        )


def downgrade() -> None:
    ids = ", ".join(f"'{item['id']}'" for item in _ITEMS)
    op.execute(f"DELETE FROM showcase_items WHERE id IN ({ids})")
