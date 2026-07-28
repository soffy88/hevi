"""add cost_usd to shot_verdict

INC-004 §4.3(2026-07-19):L4 旗舰 provider 路由某镜时的实付美元。None = 本地免费路
(standard tier,绝大多数镜头)。攒"key 镜占比 × 单价"的真实数据,判断成本模型(90/10)
准不准靠它——这类数据没法补录,今天不落库就是永久丢掉从现在起的信号。

跟 §6.2 四支柱里的 cost(校验算力)不是一回事,不合并进 checks_json——想按成本模型聚合
查询,一个真正的列比 JSONB 里挖字段好查得多。

Revision ID: eaff3a92445c
Revises: c7d8e9f0a1b2
Create Date: 2026-07-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eaff3a92445c"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shot_verdict", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("shot_verdict", "cost_usd")
