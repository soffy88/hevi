"""Q9:cost_class → 金额/时长映射(部署配置,非硬编码)。

cost_class 是相对档位;真金白银由部署侧配置。estimate 汇总一次 rerun_plan 的
上限,供审批前展示。未配置映射 → 报 COST_TABLE_UNCONFIGURED,不猜金额。
"""

from __future__ import annotations

from dataclasses import dataclass

from hevi.creative.direction_verify.errors import VerifyError

COST_CLASSES = ("none", "low", "medium", "high")


@dataclass(frozen=True)
class CostBound:
    cost_class: str
    max_usd: float
    max_minutes: float


@dataclass(frozen=True)
class CostTable:
    """部署配置:每档上限。未列出的档位视为未配置。"""

    bounds: dict[str, CostBound]

    def bound(self, cost_class: str) -> CostBound:
        found = self.bounds.get(cost_class)
        if found is None:
            raise VerifyError(f"cost table missing {cost_class!r}",
                              code="COST_TABLE_UNCONFIGURED")
        return found

    def estimate(self, rerun_plan: list[tuple[str, str]]) -> CostBound:
        """rerun_plan: [(stage, cost_class)] → 取最高档(保守)。"""
        worst = "none"
        rank = {name: i for i, name in enumerate(COST_CLASSES)}
        for _stage, cost_class in rerun_plan:
            if rank[cost_class] > rank[worst]:
                worst = cost_class
        return self.bound(worst)


def default_cost_table(*, video_shot_usd: float = 0.40, video_shot_minutes: float = 3.0,
                       render_film_usd: float = 0.10, render_film_minutes: float = 10.0) -> CostTable:
    """保守默认:high = 一次视频生成镜头;medium = 整片渲染;low/none 近零。"""
    return CostTable({
        "none": CostBound("none", 0.0, 0.0),
        "low": CostBound("low", 0.05, 1.0),
        "medium": CostBound("medium", render_film_usd, render_film_minutes),
        "high": CostBound("high", video_shot_usd, video_shot_minutes),
    })