from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    reference_images: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # 3O manifest §C1:身份/视觉向量(建角色时从首张参考图离线算,CLIP L2-归一化)。
    # 是 L3 审片"还是不是这个人/同一风格"的锚 + 跨 provider 一致性度量基准。nullable:
    # 老数据/无参考图/算失败时为空,不阻断建角色。全图向量(kind="style",不裁剪)。
    identity_embedding: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    # 多区域 embedding(HEVI 路线图 Phase2 #34):脸部区域向量(kind="face",几何裁剪
    # 启发式,见 subject_embed.py 顶部注释——不是真人脸检测,只是常见半身像构图的
    # 上半部/居中裁剪)。跟 identity_embedding(全图)分开存,审片时两个区域各比一次
    # 取更像的那个,而不是混在一张向量里——背影/侧身镜头裁不到脸时还能靠全图向量
    # 兜底,不会因为"看不清脸"就整体判定身份不符。
    identity_embedding_face: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    # 参考素材角色标签(设计文档 §5.2):跟 subject_type(character/portrait/product/scene)
    # 正交的另一个维度——同一张参考图可能是"身份锚点"(驱动 i2v 锁脸/身份向量),也可能
    # 只是"构图/氛围参考"(不代表这个人长什么样,只是想要类似的取景)。keyed by
    # reference_images 里的路径,value 是自由文本角色标签(不强制枚举——常见值见
    # subject_service.py 的 set_reference_role docstring)。未打标的图不受影响,现有
    # "reference_images[0] 是封面/锁脸图" 的既定行为不因这个字段的存在而改变。
    reference_roles: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
