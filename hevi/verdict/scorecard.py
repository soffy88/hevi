"""shot_scorecard —— 镜头评分卡(hevi 参考实现,L3 裁决;待回迁 oskill)。

3O manifest §C4。是 `oskill.mllm_frame_consistency_check`(仅 vlm_score)的**超集**:
  identity_score = 候选帧 CLIP 向量 vs Subject.identity_embedding 余弦(C1 锚,真·图对图)
  style_score    = vs StylePack 基准帧向量余弦(可选)
  vlm_score      = 本地 Qwen-VL 打分(可选,C2)
  checks         = 确定性项(时长/字幕/响度,pass-through)
→ 聚合成 Scorecard{best_frame, passed, identity/style/vlm_score, hints}。

**这补上 C2 的遗留**:consistency 不再把 reference 当文本发,而是用 C1 的身份向量做真正的
图对图比对 —— 双变体里挑"更像锁定角色"的那个。裁决**阈值/策略**留 hevi(护城河),
可复用的**打分机制**是这里(将来搬 oskill)。

candidate_frames 是候选 **.mp4**(omodul consistency_fn 契约),内部抽代表帧再打分;
best_frame 返回**候选原路径**(mp4),供 omodul 采纳为该镜头成片。
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.subjects.subject_embed import SubjectEmbedError, cosine_similarity, subject_embed
from hevi.verdict.frame_extract import FrameExtractError, extract_representative_frame

logger = logging.getLogger(__name__)


@dataclass
class Scorecard:
    best_frame: Path
    best_index: int
    passed: bool
    identity_score: float = 0.0
    style_score: float = 0.0
    vlm_score: float = 0.0
    checks: dict[str, Any] = field(default_factory=dict)
    hints: list[str] = field(default_factory=list)
    per_candidate: list[dict[str, Any]] = field(default_factory=list)


def _score_one(
    candidate: Path,
    tmpdir: str,
    idx: int,
    subject_ref_embedding: list[float] | None,
    style_ref_embedding: list[float] | None,
) -> dict[str, Any]:
    """抽帧 + 算 identity/style 分。失败 → 分 0 + reason,不抛(不断整条链)。"""
    rec: dict[str, Any] = {
        "index": idx,
        "candidate": str(candidate),
        "identity": 0.0,
        "style": 0.0,
        "ok": False,
    }
    try:
        frame = extract_representative_frame(candidate, Path(tmpdir) / f"cand_{idx}.png")
        emb = subject_embed(image_path=frame, kind="face")
        if subject_ref_embedding:
            rec["identity"] = cosine_similarity(emb, subject_ref_embedding)
        if style_ref_embedding:
            rec["style"] = cosine_similarity(emb, style_ref_embedding)
        rec["ok"] = True
    except (FrameExtractError, SubjectEmbedError) as e:
        rec["reason"] = str(e)
        logger.warning("scorecard: candidate %d scored 0 (%s)", idx, e)
    return rec


def shot_scorecard(
    *,
    candidate_frames: list[Path],
    subject_ref_embedding: list[float] | None = None,
    style_ref_embedding: list[float] | None = None,
    deterministic: dict[str, Any] | None = None,
    identity_floor: float = 0.2,
    config: dict[str, Any] | None = None,
) -> Scorecard:
    """给候选镜头打分并挑最优。

    combined = identity(有锚) else style else 0.5。best = argmax(combined)。
    passed = best identity >= identity_floor(极低阈,仅拦全废;主价值在**选对变体**,非拦门)。
    无候选 → ValueError;有锚但全部抽帧/嵌入失败 → 退化选第一个、passed=True(不阻断)。
    """
    if not candidate_frames:
        raise ValueError("candidate_frames must not be empty")

    # 无任何锚 → 无打分依据,直接采纳第一个(不做无谓的抽帧/嵌入)。
    if not subject_ref_embedding and not style_ref_embedding:
        return Scorecard(
            best_frame=Path(candidate_frames[0]),
            best_index=0,
            passed=True,
            per_candidate=[
                {"index": i, "candidate": str(c), "identity": 0.0, "style": 0.0}
                for i, c in enumerate(candidate_frames)
            ],
        )

    with tempfile.TemporaryDirectory(prefix="scorecard_") as td:
        recs = [
            _score_one(Path(c), td, i, subject_ref_embedding, style_ref_embedding)
            for i, c in enumerate(candidate_frames)
        ]

    def _combined(r: dict[str, Any]) -> float:
        if subject_ref_embedding:
            return r["identity"]
        if style_ref_embedding:
            return r["style"]
        return 0.5

    best_i = max(range(len(recs)), key=lambda i: _combined(recs[i]))
    best = recs[best_i]
    hints: list[str] = []
    if subject_ref_embedding and best["identity"] < identity_floor:
        hints.append(
            f"身份匹配偏低(best identity={best['identity']:.2f} < {identity_floor}):"
            "疑非锁定角色,建议重生成或换参考图"
        )
    if not any(r["ok"] for r in recs):
        hints.append("全部候选抽帧/嵌入失败 → 退化选第一个")

    passed = (not subject_ref_embedding) or best["identity"] >= identity_floor
    return Scorecard(
        best_frame=Path(candidate_frames[best_i]),
        best_index=best_i,
        passed=passed,
        identity_score=best["identity"],
        style_score=best["style"],
        checks=dict(deterministic or {}),
        hints=hints,
        per_candidate=recs,
    )


def make_scorecard_consistency_fn(
    subject_ref_embedding: list[float] | None,
    *,
    style_ref_embedding: list[float] | None = None,
    identity_floor: float = 0.2,
) -> Any:
    """→ 一个符合 omodul consistency_fn 契约的 async fn(身份锚驱动的双变体选优)。

    契约(见 omodul.agentic_longvideo_pipeline):
      result = await consistency_fn(mllm=..., candidate_frames=[...mp4], reference=..., criteria=...)
      result.best_frame  # Path(候选 mp4)
      result.passed      # bool
    评分卡(重:CLIP 嵌入 + PyAV 解码)丢线程池,不阻塞事件循环。
    """
    import asyncio
    from types import SimpleNamespace

    async def _consistency_fn(*, candidate_frames: list[Path], **_kw: Any) -> Any:
        sc = await asyncio.to_thread(
            shot_scorecard,
            candidate_frames=candidate_frames,
            subject_ref_embedding=subject_ref_embedding,
            style_ref_embedding=style_ref_embedding,
            identity_floor=identity_floor,
        )
        logger.info(
            "scorecard: 选 v%d(identity=%.3f, passed=%s)%s",
            sc.best_index,
            sc.identity_score,
            sc.passed,
            f" hints={sc.hints}" if sc.hints else "",
        )
        return SimpleNamespace(best_frame=sc.best_frame, passed=sc.passed, scorecard=sc)

    return _consistency_fn
