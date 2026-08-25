"""3O §3 Task 3.2: Presenter 模型。

新代码请直接 import hevi.digital_human.models.Presenter。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


class Presenter(BaseModel):
    """A reusable speaking/on-camera profile built on a Subject asset."""

    model_config = ConfigDict(populate_by_name=True)

    # Compatibility metadata for older integrations that imported Presenter
    # as a SQLAlchemy model.  Persistence now belongs to presenters.repository
    # and this class is a Pydantic configuration model, but exposing the old
    # shape keeps introspection-only callers working during the migration.
    __tablename__: ClassVar[str] = "presenters"
    __table__: ClassVar[Any] = type(
        "_PresenterTableCompat",
        (),
        {"columns": frozenset({"id", "user_id", "name", "subject_id", "voice_profile_id", "performance", "motion", "lipsync", "delivery_json", "description", "created_at", "updated_at"})},
    )()

    id: uuid.UUID = Field(default_factory=uuid.uuid4, alias="_id")
    user_id: str = ""
    name: str = ""
    subject_id: str | None = None
    voice_profile_id: str | None = None
    performance: str = "narrator"
    motion: str = "picture_in_picture"
    lipsync: str = "none"
    delivery_json: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── 便捷工厂 ─────────────────────────────────────


def make_presenter(
    user_id: str,
    name: str,
    subject_id: str | None = None,
    voice_profile_id: str | None = None,
    performance: str = "narrator",
    motion: str = "picture_in_picture",
    lipsync: str = "none",
) -> Presenter:
    """创建 Presenter 实例。"""
    return Presenter(
        user_id=user_id,
        name=name,
        subject_id=subject_id,
        voice_profile_id=voice_profile_id,
        performance=performance,
        motion=motion,
        lipsync=lipsync,
    )
