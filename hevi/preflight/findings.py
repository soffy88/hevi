"""preflight.findings —— 门禁结论的数据结构。

级别语义（硬性）：
- FAIL：拦住，不许烧 credits；人工 override 须留理由才放行。
- WARN：放行，但须人眼确认（或接受风险）。
- INFO：通过项／提示，不阻塞。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Finding:
    level: str  # FAIL | WARN | INFO
    code: str
    message: str
    beat_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "beat_id": self.beat_id,
            "detail": self.detail,
        }


@dataclass
class GateReport:
    beat_id: str
    model: str
    verdict: str  # PASS | WARN | FAIL
    findings: list[Finding] = field(default_factory=list)
    estimated_cost: dict[str, Any] = field(default_factory=dict)
    human_checklist: list[str] = field(default_factory=list)
    override_reason: str = ""
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "model": self.model,
            "verdict": self.verdict,
            "blocked": self.blocked,
            "fail_count": sum(1 for f in self.findings if f.level == "FAIL"),
            "warn_count": sum(1 for f in self.findings if f.level == "WARN"),
            "findings": [f.to_dict() for f in self.findings],
            "estimated_cost": self.estimated_cost,
            "human_checklist": self.human_checklist,
            "override_reason": self.override_reason,
        }
