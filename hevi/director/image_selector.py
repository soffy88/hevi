"""最佳图像选择器（对标 ViMax best_image_selector.py）。

生成 N 张候选图像，通过评分或 LLM 评估选择最佳的一张。

评分维度：
  - 构图合理性（构图居中、主体突出）
  - 角色一致性（与参考肖像的匹配度）
  - 画质（清晰度、色彩、噪点）
  - prompt 遵循度（与生成提示词的匹配度）
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class CandidateImage:
    """候选图像。"""

    index: int
    path: Path
    prompt: str = ""
    score: float = 0.0
    notes: str = ""

    @property
    def exists(self) -> bool:
        return self.path.exists()


@dataclass
class SelectionResult:
    """选择结果。"""

    best: CandidateImage
    all_candidates: list[CandidateImage] = field(default_factory=list)
    strategy: str = "score"  # "score" | "llm" | "first_valid"
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_index": self.best.index,
            "best_path": str(self.best.path),
            "best_score": self.best.score,
            "strategy": self.strategy,
            "reasoning": self.reasoning,
            "candidates": [
                {
                    "index": c.index,
                    "path": str(c.path),
                    "score": c.score,
                    "exists": c.exists,
                }
                for c in self.all_candidates
            ],
        }


# ── 启发式评分 ────────────────────────────────────────────────────────


def score_image_file_size(path: Path, *, ideal_bytes: int = 500_000) -> float:
    """基于文件大小的启发式评分。

    假设：合理大小的文件更可能是有效图像（太小=损坏，太大=噪声过多）。
    """
    if not path.exists():
        return 0.0
    size = path.stat().st_size
    if size < 1000:
        return 0.1  # 太小
    ratio = size / ideal_bytes
    if ratio < 0.5:
        return 0.5 + ratio
    elif ratio > 3.0:
        return 0.7  # 过大
    return min(1.0, 0.8 + (1.0 - abs(ratio - 1.0)) * 0.2)


def score_image_dimensions(path: Path, *, ideal_ratio: float = 16 / 9) -> float:
    """基于尺寸的评分（横屏优先）。"""
    try:
        from hevi.utils.image_guard import get_image_dimensions
        dims = get_image_dimensions(path)
        if dims.is_portrait:
            return 0.3
        ratio_diff = abs(dims.aspect_ratio - ideal_ratio) / ideal_ratio
        return max(0.0, 1.0 - ratio_diff * 0.5)
    except Exception:
        return 0.5


def score_image_basic(path: Path) -> float:
    """基础文件有效性评分。"""
    if not path.exists():
        return 0.0
    size = path.stat().st_size
    if size < 100:
        return 0.0
    # 检查是否是有效的 PNG/JPEG
    try:
        with open(path, "rb") as f:
            header = f.read(8)
        if header[:4] == b'\x89PNG':
            return 0.9  # valid PNG
        if header[:2] == b'\xff\xd8':
            return 0.9  # valid JPEG
        return 0.3  # unknown format
    except Exception:
        return 0.1


# ── LLM 评分协议 ──────────────────────────────────────────────────────

LLMScoreFn = Callable[
    [list[Path], str],
    Coroutine[Any, Any, list[float]],
]
"""LLM 评分函数：(image_paths, prompt) → [score_per_image]"""


async def _default_llm_score(
    paths: list[Path], prompt: str
) -> list[float]:
    """默认 LLM 评分（回退到启发式）。"""
    scores: list[float] = []
    for p in paths:
        s = score_image_basic(p)
        s += score_image_file_size(p) * 0.5
        s += score_image_dimensions(p) * 0.3
        scores.append(min(1.0, s / 1.8))
    return scores


# ── 核心选择逻辑 ──────────────────────────────────────────────────────


async def select_best_image(
    candidates: list[CandidateImage],
    prompt: str = "",
    *,
    llm_score: LLMScoreFn | None = None,
    min_score: float = 0.3,
) -> SelectionResult:
    """从候选中选择最佳图像。

    Args:
        candidates: 候选图像列表
        prompt: 生成提示词（用于 LLM 评估）
        llm_score: LLM 评分函数（可选）
        min_score: 最低可接受评分

    Returns:
        SelectionResult
    """
    # 过滤存在的候选
    valid = [c for c in candidates if c.exists]
    if not valid:
        raise ValueError("no valid candidate images found")

    if len(valid) == 1:
        valid[0].score = score_image_basic(valid[0].path)
        return SelectionResult(
            best=valid[0],
            all_candidates=candidates,
            strategy="first_valid",
            reasoning="only one valid candidate",
        )

    # 获取评分
    score_fn = llm_score or _default_llm_score
    paths = [c.path for c in valid]
    scores = await score_fn(paths, prompt)

    # 赋值评分
    for c, s in zip(valid, scores):
        c.score = s

    # 选最高分
    best = max(valid, key=lambda c: c.score)

    if best.score < min_score:
        logger.warning(
            "best image score %.2f < min %.2f, selecting anyway",
            best.score, min_score,
        )

    return SelectionResult(
        best=best,
        all_candidates=candidates,
        strategy="llm" if llm_score else "score",
        reasoning=f"highest score: {best.score:.2f} (index={best.index})",
    )


# ── 生成 + 选择一体化 ─────────────────────────────────────────────────

ImageGenFn = Callable[
    [str, list[Path], Path],
    Coroutine[Any, Any, Path],
]


async def generate_and_select(
    prompt: str,
    reference_images: list[Path],
    output_dir: Path,
    *,
    n_candidates: int = 3,
    image_gen: ImageGenFn | None = None,
    llm_score: LLMScoreFn | None = None,
    task_id: str = "shot",
) -> SelectionResult:
    """生成 N 张候选图像并选择最佳。

    Args:
        prompt: 生成提示词
        reference_images: 参考图像列表
        output_dir: 输出目录
        n_candidates: 候选数量
        image_gen: 图像生成函数
        llm_score: LLM 评分函数
        task_id: 任务标识

    Returns:
        SelectionResult
    """
    from hevi.director.portrait_triptych import _default_image_gen

    gen_fn = image_gen or _default_image_gen
    output_dir.mkdir(parents=True, exist_ok=True)

    # 并行生成 N 张候选
    candidates: list[CandidateImage] = []
    tasks = []
    for i in range(n_candidates):
        out_path = output_dir / f"{task_id}_candidate_{i:02d}.png"
        candidate = CandidateImage(index=i, path=out_path, prompt=prompt)
        candidates.append(candidate)
        tasks.append(gen_fn(prompt, reference_images, out_path))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 标记失败的候选
    for c, r in zip(candidates, results):
        if isinstance(r, Exception):
            logger.warning("candidate %d failed: %s", c.index, r)
            c.notes = str(r)

    # 选择最佳
    return await select_best_image(
        candidates, prompt,
        llm_score=llm_score,
    )


# ── 便捷函数 ──────────────────────────────────────────────────────────


def rank_candidates(candidates: list[CandidateImage]) -> list[CandidateImage]:
    """按评分降序排列候选。"""
    valid = [c for c in candidates if c.exists]
    return sorted(valid, key=lambda c: c.score, reverse=True)


def filter_valid(candidates: list[CandidateImage]) -> list[CandidateImage]:
    """过滤出存在且有效的候选。"""
    return [c for c in candidates if c.exists and score_image_basic(c.path) > 0.5]
