"""create shot preparation tables (INC-001 §A/§G/§I)

导演台「逐镜头准备台」的持久化地基:AI 候选 vs 人工确认实体分离(§G)、镜头就绪状态机
(§A,status 只 pending/ready,由候选态重算)、skip_extraction 逃生阀(§I)。三张表都按
(work_id, shot_id) 定位——work 本身仍是导演台的内存对象(_WORKS),这里只持久化"确认明细"
(候选 + 就绪态),不持久化镜头正文。

- shot_readiness:每镜一行,status(pending/ready)+ skip_extraction + extracted(是否提取过)。
- shot_extracted_candidates:资产候选(character/scene/prop/costume),status pending→linked|ignored。
- shot_extracted_dialogue_candidates:对白候选,status pending→accepted|ignored,带 target_name(§H)。

Revision ID: c7d8e9f0a1b2
Revises: f4b5c6d7e8a1
Create Date: 2026-07-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "f4b5c6d7e8a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shot_readiness",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_id", sa.String(64), nullable=False),
        sa.Column("shot_id", sa.String(64), nullable=False),
        # §A:只有 pending / ready 两值,由后端按 §A.1 规则重算,不由前端设置。
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        # §I:逃生阀——用户声明该镜无需提取 → 直达 ready。
        sa.Column("skip_extraction", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # §A.1 规则2:从未提取过 → pending(区别于"提取过但无候选"→ ready)。
        sa.Column("extracted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("work_id", "shot_id", name="uq_shot_readiness_work_shot"),
    )

    op.create_table(
        "shot_extracted_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_id", sa.String(64), nullable=False),
        sa.Column("shot_id", sa.String(64), nullable=False),
        # character / scene / prop / costume
        sa.Column("candidate_type", sa.String(20), nullable=False),
        sa.Column("candidate_name", sa.String(255), nullable=False),
        # pending → linked | ignored
        sa.Column("candidate_status", sa.String(20), nullable=False, server_default="pending"),
        # 关联到的真实资产 subject_id(§G:确认后回填;设计清单锁定时已建的 Subject)。
        sa.Column("linked_entity_id", sa.String(64), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_shot_extracted_candidates_work_shot",
        "shot_extracted_candidates",
        ["work_id", "shot_id"],
    )

    op.create_table(
        "shot_extracted_dialogue_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_id", sa.String(64), nullable=False),
        sa.Column("shot_id", sa.String(64), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("line_mode", sa.String(32), nullable=True),
        sa.Column("speaker_name", sa.String(255), nullable=True),
        # §H 对谁说 → eyeline 数据源。
        sa.Column("target_name", sa.String(255), nullable=True),
        # pending → accepted | ignored
        sa.Column("candidate_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("linked_dialog_line_id", sa.String(64), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_shot_extracted_dialogue_candidates_work_shot",
        "shot_extracted_dialogue_candidates",
        ["work_id", "shot_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shot_extracted_dialogue_candidates_work_shot",
        table_name="shot_extracted_dialogue_candidates",
    )
    op.drop_table("shot_extracted_dialogue_candidates")
    op.drop_index("ix_shot_extracted_candidates_work_shot", table_name="shot_extracted_candidates")
    op.drop_table("shot_extracted_candidates")
    op.drop_table("shot_readiness")
