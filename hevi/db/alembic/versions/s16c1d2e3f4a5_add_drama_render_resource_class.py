"""add drama_render to the video_tasks resource_class check

Revision ID: s16c1d2e3f4a5
Revises: s10b2c3d4e5f6
Create Date: 2026-11-09 08:20:00

The dedicated drama render worker claims only ``resource_class='drama_render'``;
the generic worker excludes it.  The original check constraint predates that
class, so widen it.
"""

from __future__ import annotations

from alembic import op

revision = "s16c1d2e3f4a5"
down_revision = "s10b2c3d4e5f6"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_video_tasks_scheduler_resource_class"
_CLASSES = ("any", "cpu", "gpu-video", "gpu-audio", "cloud", "drama_render")


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "video_tasks", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "video_tasks",
        "resource_class IN (" + ", ".join(f"'{item}'" for item in _CLASSES) + ")",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "video_tasks", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "video_tasks",
        "resource_class IN ('any', 'cpu', 'gpu-video', 'gpu-audio', 'cloud')",
    )
