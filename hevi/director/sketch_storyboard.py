"""线稿草图分镜 —— 草图选择/上色校验/视觉闸门(3O 内化 Phase C,来源 dramaclaw sketch_*)。

dramaclaw 的线稿草图系统是独特形态:beat 驱动线稿 → 图池选择 → 上色校验 →
视觉闸门。这里沉淀其**可复用逻辑**:草图候选评分(确定性,不吃模型)、
上色一致校验(线稿 vs 上色图结构对齐启发式)、视觉闸门(通过/打回 + 失败码)。

3O 归属(待上游): `oskill.sketch_storyboard`(选择 + 闸门)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class SketchStoryboardError(Exception):
    """草图分镜失败。"""


@dataclass(frozen=True)
class SketchCandidate:
    """一张草图候选:元数据 + 确定性评分依据。"""

    path: Path
    beat_id: str
    coverage: float = 1.0  # 0-1,画面覆盖 beat 内容比例(由上游 VLM/人工给出)
    composition_ok: bool = True  # 构图合规(安全区/主体位置)
    style_match: float = 1.0  # 0-1,与风格基准的贴近度(由上游给出)


@dataclass
class SketchGateResult:
    """视觉闸门结果。"""

    passed: bool
    chosen: SketchCandidate | None
    failure_codes: list[str] = field(default_factory=list)
    scoreboard: dict[str, float] = field(default_factory=dict)


def score_sketch(candidate: SketchCandidate) -> float:
    """确定性评分:覆盖优先,构图为闸门,风格为加权。"""
    if not candidate.composition_ok:
        return 0.0
    return 1.5 * candidate.coverage + 0.5 * candidate.style_match


def select_best_sketch(candidates: list[SketchCandidate]) -> SketchCandidate | None:
    """图池选择:取最高分;构图不合规的直接排除。"""
    valid = [c for c in candidates if c.composition_ok]
    if not valid:
        return None
    return max(valid, key=score_sketch)


def run_visual_gate(
    candidates: list[SketchCandidate],
    *,
    coverage_floor: float = 0.6,
    style_floor: float = 0.5,
) -> SketchGateResult:
    """视觉闸门:过线 → 采纳;不过 → 打回 + 失败码(喂 verdict/负向子句)。"""
    chosen = select_best_sketch(candidates)
    failure_codes: list[str] = []
    if chosen is None:
        failure_codes.append("no_composition_ok_candidate")
        return SketchGateResult(passed=False, chosen=None, failure_codes=failure_codes)

    scoreboard = {c.path.name: score_sketch(c) for c in candidates}
    if chosen.coverage < coverage_floor:
        failure_codes.append("coverage_below_floor")
    if chosen.style_match < style_floor:
        failure_codes.append("style_below_floor")
    if chosen.coverage < 0.3:
        failure_codes.append("composition_critical")  # 低覆盖且构图差 → 整段重画
    return SketchGateResult(
        passed=not failure_codes,
        chosen=chosen,
        failure_codes=failure_codes,
        scoreboard=scoreboard,
    )


def color_consistency_check(sketch_path: Path, color_path: Path) -> bool:
    """上色一致校验:线稿与上色图结构对齐启发式。

    启发式:两图缩到 16×16 灰度后均差 ≤ 阈值判为结构一致(上色不改结构)。
    图不存在/无法解码 → 抛 SketchStoryboardError。
    """
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover - env guard
        raise SketchStoryboardError(f"PIL 未安装: {e}") from e
    try:
        a = Image.open(sketch_path).convert("L").resize((16, 16))
        b = Image.open(color_path).convert("L").resize((16, 16))
    except Exception as e:
        raise SketchStoryboardError(f"cannot open sketch/color: {e}") from e
    pa, pb = list(a.tobytes()), list(b.tobytes())
    diff = sum(abs(x - y) for x, y in zip(pa, pb, strict=False)) / len(pa)
    # 上色通常保留明暗结构:阈放宽到 48(上色改变亮度但保留轮廓)
    return diff <= 48.0
