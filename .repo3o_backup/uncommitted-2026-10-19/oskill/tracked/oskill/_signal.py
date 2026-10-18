from typing import Any, Literal

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """通用信号抽象 (告警/工单/任务/客服分诊都能用)."""

    source: str  # "prometheus" / "user_report" / "anomaly_detector"
    severity: Literal["critical", "warning", "info"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)  # 灵活字段, 不锁结构
    fingerprint: str | None = None  # caller 提供 (用于服务层去重)
