"""add selection_json to shot_states

C3 落库:shot_states 增 selection_json,存双变体选优明细(provider/variant_chosen/
consistency_score/passed/duration_s),来自 omodul v1.36.0 的 LongVideoResult.shots。
nullable —— 老数据/未产出为空。

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shot_states",
        sa.Column(
            "selection_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("shot_states", "selection_json")
