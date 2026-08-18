"""provider_scoring —— 供给层多维可解释评分(3O oskill 风格, 待回迁 oskill)。

对标 OpenMontage 的 7 维加权评分 + explain() 可解释决策日志, 补 hevi 差距 A1:
hevi 此前 provider 选择靠 ProviderRegistry + 成本路由, 元数据散在 3 张 video-only
dict, 选择不可解释、无审计日志。

本模块是**纯函数 + 显式数据**, 不 import provider SDK:
  - `ProviderScore` 7 维评分(0-1 归一) + 加权总分 + explain() 人类可读解释
  - `score_providers()` 对候选 provider 逐一评分, 返回排序列表
  - `score_candidates_from_capabilities()` 从能力声明 dict 批量构造评分上下文
  - `ProviderDecisionLog` 决策日志(JSON Lines, 追加式, 无 PII)
  - `choose_provider()` 选优 + 记日志的一体入口

评分维度与权重(对齐 OpenMontage):
  task_fit 0.30 | output_quality 0.20 | control 0.15 | reliability 0.15
  cost_efficiency 0.10 | latency 0.05 | continuity 0.05

使用: 服务层在真实选择 provider 前调用 `choose_provider`, 得到分数与解释;
决策日志写 `output_dir/provider_decisions.jsonl`(append), 供审计/路由治理回看。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

# 7 维权重(和为 1.0)。修改需同步更新 explain() 文案与测试。
DEFAULT_WEIGHTS: dict[str, float] = {
    "task_fit": 0.30,
    "output_quality": 0.20,
    "control": 0.15,
    "reliability": 0.15,
    "cost_efficiency": 0.10,
    "latency": 0.05,
    "continuity": 0.05,
}

_DIMENSION_ORDER = (
    "task_fit",
    "output_quality",
    "control",
    "reliability",
    "cost_efficiency",
    "latency",
    "continuity",
)


@dataclass(frozen=True)
class ProviderScore:
    """单 provider 对单任务上下文的评分。分数均为 0-1 归一, 越高越好。"""

    tool_name: str  # 任务类别, 如 "video/shot" / "tts/narration"
    provider: str  # provider 标识, 如 "h3_local" / "wan_2_7_maas"
    task_fit: float = 0.0
    output_quality: float = 0.0
    control: float = 0.0
    reliability: float = 0.0
    cost_efficiency: float = 0.0
    latency: float = 0.0
    continuity: float = 0.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        for dim in _DIMENSION_ORDER:
            val = getattr(self, dim)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{dim} must be in [0,1], got {val}")

    @property
    def weighted_score(self) -> float:
        return round(
            sum(getattr(self, dim) * self.weights.get(dim, 0.0) for dim in _DIMENSION_ORDER),
            4,
        )

    def explain(self) -> str:
        """人类可读的评分解释, 供决策日志/审计。"""
        parts = [f"{self.tool_name}@{self.provider}: weighted={self.weighted_score:.3f}"]
        for dim in _DIMENSION_ORDER:
            parts.append(f"{dim}={getattr(self, dim):.2f}(w{self.weights.get(dim, 0.0):.2f})")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["weighted_score"] = self.weighted_score
        return d


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def score_providers(
    tool_name: str,
    candidates: Sequence[dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
    default_scores: dict[str, float] | None = None,
) -> list[ProviderScore]:
    """对候选 provider 逐一评分。

    Args:
        tool_name: 任务类别标识(如 "video/shot")。
        candidates: 候选列表, 每项为 dict, 至少含 "provider"; 其余键为 7 维分数
            (缺省取 default_scores 对应值, 再缺省取 0)。
        weights: 维度权重覆盖(缺省 DEFAULT_WEIGHTS)。
        default_scores: 未显式给出的维度分数默认值(如按能力行的保守估计)。
    Returns:
        按 weighted_score 降序的评分列表(不含 <0 的非法项; 会跳过无 provider 键的项)。
    """
    w = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
    defaults = default_scores or {}
    scored: list[ProviderScore] = []
    for cand in candidates:
        provider = cand.get("provider")
        if not provider:
            continue
        kw: dict[str, Any] = {"tool_name": tool_name, "provider": str(provider), "weights": w}
        for dim in _DIMENSION_ORDER:
            val = cand.get(dim, defaults.get(dim, 0.0))
            kw[dim] = _clamp(val)
        scored.append(ProviderScore(**kw))
    scored.sort(key=lambda s: s.weighted_score, reverse=True)
    return scored


def choose_provider(
    tool_name: str,
    candidates: Sequence[dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
    default_scores: dict[str, float] | None = None,
    decision_log: Path | None = None,
    reason: str = "",
) -> ProviderScore | None:
    """评分选优 + 可选决策日志的一体入口。

    返回最高分 ProviderScore(候选为空 → None)。decision_log 非空时把全部候选
    评分与选中项追加写入 JSONL(无 PII, 字段仅 provider/tool_name/维度分/总分)。
    """
    scored = score_providers(
        tool_name, candidates, weights=weights, default_scores=default_scores
    )
    if not scored:
        return None
    winner = scored[0]
    if decision_log is not None:
        _append_decision(
            decision_log,
            tool_name=tool_name,
            scored=[s.to_dict() for s in scored],
            winner=winner.to_dict(),
            reason=reason,
        )
    return winner


def _append_decision(
    path: Path,
    *,
    tool_name: str,
    scored: list[dict[str, Any]],
    winner: dict[str, Any],
    reason: str,
) -> None:
    """追加一条决策记录(JSON Lines)。写失败仅记日志, 不阻断业务。"""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool_name": tool_name,
        "reason": reason,
        "winner": winner,
        "candidates": scored,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:  # pragma: no cover - 写失败不阻断
        logger.warning("provider decision log write failed (%s): %s", path, exc)


# ---------------------------------------------------------------------------
# 能力声明 → 候选构造 (hevi 差距 A1: 统一 ProviderMeta 的雏形)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityRow:
    """能力行: 与 hevi/video/provider_config.py 的 `VideoProvider` 能力声明对齐。

    scores 为 7 维分数(0-1), 缺省保守值 0。
    """

    provider: str
    tool_name: str
    scores: dict[str, float] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


def score_candidates_from_capabilities(
    rows: Sequence[CapabilityRow | dict[str, Any]],
    tool_name: str,
    *,
    weights: dict[str, float] | None = None,
) -> list[ProviderScore]:
    """从能力行列表构造评分候选。

    row 可为 CapabilityRow 或 dict(键 provider/tool_name/scores)。仅保留 tool_name
    匹配的行(便于一次声明、按任务类别筛选)。
    """
    cands: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, CapabilityRow):
            if row.tool_name != tool_name:
                continue
            cand = {"provider": row.provider, **row.scores}
        else:
            if row.get("tool_name", tool_name) != tool_name:
                continue
            cand = {"provider": row["provider"], **row.get("scores", {})}
        cands.append(cand)
    return score_providers(tool_name, cands, weights=weights)


# ---------------------------------------------------------------------------
# 决策日志读取(审计/回看)
# ---------------------------------------------------------------------------


def read_decision_log(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """读取决策日志 JSONL, 按写入顺序返回(最新在后)。limit 限制条数。"""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:  # pragma: no cover - 容忍坏行
                logger.warning("skip malformed decision log line in %s", path)
    if limit is not None:
        records = records[-limit:]
    return records


# 为将来回迁 oskill 预留的 Protocol: 本模块评分函数不依赖任何 provider SDK,
# 调用方(服务层)负责注入候选/权重。此为纯函数层, 不持状态。
ScorerCallable: Callable[..., ProviderScore | None] = choose_provider

__all__ = [
    "DEFAULT_WEIGHTS",
    "CapabilityRow",
    "ProviderScore",
    "choose_provider",
    "read_decision_log",
    "score_candidates_from_capabilities",
    "score_providers",
]
