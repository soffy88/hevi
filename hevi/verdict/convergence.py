"""收敛循环 —— 逐集/逐阶段返工轮次历史与趋势(3O 内化 Phase D,来源 dramaclaw convergence_log)。

dramaclaw 的 convergence_log:每次返工轮次记录 residual/fixed/new_failures,
喂给 show_trend CLI 与将来的收敛循环控制器。这里是确定性版本:
  - 轮次记录:episode + phase + round_num 唯一,记录残差/修复/新增失败
  - 趋势:残差是否单调下降(收敛)vs 震荡/发散
  - 建议:发散时建议降档交付 + 部分退款(retake-protocol 尝试预算)

3O 归属(待上游): `omodul.convergence_loop`(轮次日志 + 趋势)。
"""

from __future__ import annotations

import itertools
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: 判定阈值:连续两轮残差上升 = 发散;残差 < 该值 = 收敛达标。
RESIDUAL_TARGET = 0.1
DIVERGENCE_STREAK = 2


@dataclass
class ConvergenceRound:
    """一轮返工记录。"""

    episode_num: int
    phase: str
    round_num: int
    residual_count: int
    fixed_count: int
    new_failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "episode_num": self.episode_num,
            "phase": self.phase,
            "round_num": self.round_num,
            "residual_count": self.residual_count,
            "fixed_count": self.fixed_count,
            "new_failures": self.new_failures,
        }


class ConvergenceLog:
    """轮次日志:按 (episode, phase, round) 追加,round 自动编号。"""

    def __init__(self, rounds: list[ConvergenceRound] | None = None) -> None:
        self._rounds: list[ConvergenceRound] = sorted(
            rounds or [],
            key=lambda r: (r.episode_num, r.phase, r.round_num),
        )

    def next_round_num(self, episode_num: int, phase: str) -> int:
        relevant = (
            r.round_num
            for r in self._rounds
            if r.episode_num == episode_num and r.phase == phase
        )
        return max(relevant, default=0) + 1

    def add_round(
        self,
        *,
        episode_num: int,
        phase: str,
        residual_count: int,
        fixed_count: int,
        new_failures: list[str] | None = None,
    ) -> ConvergenceRound:
        record = ConvergenceRound(
            episode_num=episode_num,
            phase=phase,
            round_num=self.next_round_num(episode_num, phase),
            residual_count=residual_count,
            fixed_count=fixed_count,
            new_failures=list(new_failures or []),
        )
        self._rounds.append(record)
        return record

    def rounds(
        self, episode_num: int | None = None, phase: str | None = None
    ) -> list[ConvergenceRound]:
        out = self._rounds
        if episode_num is not None:
            out = [r for r in out if r.episode_num == episode_num]
        if phase is not None:
            out = [r for r in out if r.phase == phase]
        return out

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                [r.to_dict() for r in self._rounds], ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> ConvergenceLog:
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            [
                ConvergenceRound(
                    episode_num=int(item["episode_num"]),
                    phase=item["phase"],
                    round_num=int(item["round_num"]),
                    residual_count=int(item["residual_count"]),
                    fixed_count=int(item["fixed_count"]),
                    new_failures=list(item.get("new_failures", [])),
                )
                for item in raw
            ]
        )


def _strictly_rising(values: list[int]) -> bool:
    """连续两两严格上升。"""
    return all(b > a for a, b in itertools.pairwise(values))

def trend(
    log: ConvergenceLog,
    *,
    episode_num: int | None = None,
    phase: str | None = None,
) -> dict[str, object]:
    """趋势判定:converging(收敛)/oscillating(震荡)/diverging(发散)/stable(达标)。

    Rules:
      - 无轮次 → "no_data"
      - 最新残差 < RESIDUAL_TARGET → "stable"(已达标)
      - 最近 DIVERGENCE_STREAK 轮残差严格上升 → "diverging"
      - 残差方向交替 → "oscillating"
      - 其余 → "converging"
    """
    rounds = log.rounds(episode_num, phase)
    if not rounds:
        return {"status": "no_data", "rounds": 0}
    residuals = [r.residual_count for r in rounds]
    latest = residuals[-1]
    base: dict[str, object] = {"rounds": len(rounds), "latest_residual": latest}

    if latest < RESIDUAL_TARGET:
        return {"status": "stable", **base}

    if len(residuals) >= DIVERGENCE_STREAK + 1 and _strictly_rising(
        residuals[-DIVERGENCE_STREAK:]
    ):
        return {
            "status": "diverging",
            **base,
            "suggestion": (
                "发散:停止重掷,走降级交付 + 部分退款;"
                "先诊断根因,一次只改一个变量"
            ),
        }

    direction_changes = sum(
        1
        for a, b, c in zip(residuals, residuals[1:], residuals[2:], strict=False)
        if (b > a) != (c > b)
    )
    if direction_changes >= 2:
        return {
            "status": "oscillating",
            **base,
            "suggestion": "震荡:变量混杂,改为一次只改一个变量;或换档位/换 provider",
        }

    return {"status": "converging", **base}
