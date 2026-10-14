"""Backlot 分镜联系表审批门 —— 逐场景缩略图 + 提示词 + 成本 + 质量分 + 审批写回。

对标 OpenMontage Backlot 的 contact sheet 审批门(只读设计参考, 本文件自写):
制片跑到分镜阶段, 不该一路黑箱合成到底。联系表把每个场景摊开: 一张缩略图、
生成提示词、花了多少钱、质量多少分 —— 人一眼扫过去, 逐场景 approve / reject。
reject 的场景**写回状态**, 下游排产读到就重跑, 而不是带着一个已知不好的镜头
继续往下走。

三条硬规则:

1. **质量分是量出来的, 不是声明的。** `measure_quality()` 自己抽帧、自己算 luma /
   帧差; 调用方给一个 ``quality_score`` 数字进来不会被采信(只记进
   ``declared_score`` 供对照)。量不出来的一维写进 ``unmeasured``, 绝不当 0 分。
2. **approve 必须有据。** `decide()` 要求非空 reason 才允许 reject; approve 记录
   裁决人、理由与时间戳, 并 append 一条不可变 decision 记录(可回放)。
3. **写回即事实。** 裁决落盘到 ``<backlot_dir>/<run_id>/shots.json``, 上层
   (pipeline / ops / E2E) 读同一个文件, 没有第二份真相。
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SHOT_PENDING = "pending"
SHOT_APPROVED = "approved"
SHOT_REJECTED = "rejected"

#: 质量分权重。运动权重最高 —— 分镜审批看的是"这条镜头有没有在动"。
_QUALITY_WEIGHTS = {"exposure": 0.30, "contrast": 0.20, "motion": 0.50}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ShotDecision:
    """一次不可变的裁决记录(可回放)。"""

    scene_id: str
    decision: str  # approved | rejected
    reason: str = ""
    reviewer: str = "anonymous"
    ts: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoryboardShot:
    """联系表上的一格。"""

    scene_id: str
    index: int = 0
    title: str = ""
    prompt: str = ""
    thumbnail: str = ""
    source_path: str = ""
    duration_s: float = 0.0
    cost_usd: float = 0.0
    status: str = SHOT_PENDING
    quality: dict[str, Any] = field(default_factory=dict)
    declared_score: float | None = None
    decisions: list[ShotDecision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decisions"] = [dec.to_dict() for dec in self.decisions]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoryboardShot:
        return cls(
            scene_id=str(data["scene_id"]),
            index=int(data.get("index") or 0),
            title=str(data.get("title") or ""),
            prompt=str(data.get("prompt") or ""),
            thumbnail=str(data.get("thumbnail") or ""),
            source_path=str(data.get("source_path") or ""),
            duration_s=float(data.get("duration_s") or 0.0),
            cost_usd=float(data.get("cost_usd") or 0.0),
            status=str(data.get("status") or SHOT_PENDING),
            quality=dict(data.get("quality") or {}),
            declared_score=data.get("declared_score"),
            decisions=[
                ShotDecision(
                    scene_id=str(d.get("scene_id") or ""),
                    decision=str(d.get("decision") or ""),
                    reason=str(d.get("reason") or ""),
                    reviewer=str(d.get("reviewer") or "anonymous"),
                    ts=str(d.get("ts") or ""),
                )
                for d in (data.get("decisions") or [])
            ],
        )


# ---------------------------------------------------------------------------
# 质量分:自己量
# ---------------------------------------------------------------------------


def measure_quality(
    source: str | Path,
    *,
    work_dir: str | Path,
    motion_delta_floor: float = 1.0,
) -> dict[str, Any]:
    """Measure a scene's quality from its pixels. Never returns a bare number.

    Returns ``{score, components, measured, unmeasured, notes}``.  ``score`` is
    only present when every weighted dimension was actually measured; otherwise
    the caller sees ``score: None`` plus ``unmeasured`` and must not treat the
    missing dimension as healthy.
    """
    from hevi.layer4_legacy.review.oprim_impl.frames import (
        frame_stats,
        interframe_delta,
        sample_frames,
    )
    from hevi.layer4_legacy.review.oprim_impl.media import MediaError
    from hevi.layer4_legacy.review.oskill_impl.quality_score import (
        aggregate_score,
    )
    from hevi.verdict.frame_extract import FrameExtractError, extract_representative_frame

    src = Path(source)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "source": str(src),
        "measured": {},
        "unmeasured": [],
        "notes": [],
    }
    if not src.exists():
        out["notes"].append(f"source not found: {src}")
        out["unmeasured"] = list(_QUALITY_WEIGHTS)
        return out

    # 1) representative frame -> luma statistics
    try:
        thumb = extract_representative_frame(src, work / f"{src.stem}_thumb.png")
    except FrameExtractError as exc:
        out["notes"].append(f"representative frame failed: {exc}")
        out["unmeasured"] = list(_QUALITY_WEIGHTS)
        return out
    out["thumbnail"] = str(thumb)

    check = frame_stats(path=thumb, index=0, timestamp_s=0.0).to_dict()
    out["frame"] = check
    if check.get("is_broken"):
        out["notes"].append("代表帧不可解码(破图)")
        out["unmeasured"] = list(_QUALITY_WEIGHTS)
        return out

    mean_luma = float(check.get("mean_luma") or 0.0)
    stdev_luma = float(check.get("stdev_luma") or 0.0)
    out["measured"]["mean_luma"] = round(mean_luma, 3)
    out["measured"]["stdev_luma"] = round(stdev_luma, 3)
    if check.get("is_black"):
        out["notes"].append(f"代表帧近黑 (mean luma {mean_luma:.1f})")
    if check.get("is_flat"):
        out["notes"].append(f"代表帧平帧 (luma stdev {stdev_luma:.2f})")

    # 2) motion -> two dense frames and their measured luma delta
    delta: float | None = None
    if src.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
        try:
            pair = sample_frames(path=src, out_dir=work / f"{src.stem}_motion", count=2)
            if len(pair) >= 2:
                delta = float(interframe_delta(frames=pair[:2])[0])
                out["measured"]["motion_delta"] = round(delta, 4)
        except (MediaError, OSError) as exc:
            out["notes"].append(f"运动量测失败: {exc}")
    else:
        out["notes"].append("静帧素材: 无运动可量, 运动维不计入")

    components = {
        "exposure": aggregate_score("exposure", mean_luma),
        "contrast": aggregate_score("contrast", stdev_luma),
        "motion": aggregate_score("motion", delta) if delta is not None else None,
    }
    out["components"] = components
    scored = {k: v for k, v in components.items() if v is not None}
    out["unmeasured"] = sorted(set(_QUALITY_WEIGHTS) - set(scored))
    if out["unmeasured"]:
        # 部分维度量不到 -> 不给总分(部分分会被下游当成"还行")
        out["score"] = None
        out["partial_score"] = (
            round(
                sum(scored[k] * _QUALITY_WEIGHTS[k] for k in scored)
                / max(sum(_QUALITY_WEIGHTS[k] for k in scored), 1e-6),
                4,
            )
            if scored
            else None
        )
        out["notes"].append(f"未量测维度 {out['unmeasured']}: 不给总分, 只给 partial_score")
    else:
        out["score"] = round(sum(components[k] * _QUALITY_WEIGHTS[k] for k in _QUALITY_WEIGHTS), 4)
        out["partial_score"] = out["score"]
    out["weights"] = dict(_QUALITY_WEIGHTS)
    return out


# ---------------------------------------------------------------------------
# 板: 落盘 + 裁决写回
# ---------------------------------------------------------------------------


class StoryboardBoard:
    """一个 run 的分镜联系表。落盘在 ``<root>/<run_id>/shots.json``。"""

    def __init__(self, root: str | Path, run_id: str) -> None:
        if not run_id or any(ch in run_id for ch in ("/", "\\", "..")):
            raise ValueError(f"invalid run_id: {run_id!r}")
        self.run_id = run_id
        safe = "".join(c for c in run_id if c.isalnum() or c in "_-")
        self.dir = Path(root) / safe
        self.path = self.dir / "shots.json"
        self._shots: dict[str, StoryboardShot] = {}
        if self.path.is_file():
            self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("backlot board load failed (%s): %s", self.path, exc)
            return
        self._shots = {
            str(s["scene_id"]): StoryboardShot.from_dict(s) for s in (raw.get("shots") or [])
        }

    def save(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": self.run_id,
            "updated_at": _utc_now(),
            "shots": [s.to_dict() for s in self.shots()],
            "summary": self.summary(),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    # -- mutations ---------------------------------------------------------
    def upsert(self, shot: StoryboardShot) -> StoryboardShot:
        """写入/更新一格。已有裁决的格子不会被上游的默认值覆盖。"""
        if not shot.thumbnail:
            shot.thumbnail = str((shot.quality or {}).get("thumbnail") or "")
        existing = self._shots.get(shot.scene_id)
        if existing is not None:
            shot.decisions = list(existing.decisions)
            shot.status = existing.status
            if shot.quality == {}:
                shot.quality = existing.quality
            if not shot.thumbnail:
                shot.thumbnail = existing.thumbnail
        self._shots[shot.scene_id] = shot
        self.save()
        return shot

    def decide(
        self,
        scene_id: str,
        *,
        decision: str,
        reason: str = "",
        reviewer: str = "anonymous",
    ) -> StoryboardShot:
        if decision not in (SHOT_APPROVED, SHOT_REJECTED):
            raise ValueError(f"decision must be approved|rejected, got {decision!r}")
        shot = self._shots.get(scene_id)
        if shot is None:
            raise KeyError(f"unknown scene_id: {scene_id!r}")
        if decision == SHOT_REJECTED and not reason.strip():
            raise ValueError("reject 必须写理由: 审批门要能追责, 不能无声否掉一个镜头")
        shot.status = decision
        shot.decisions.append(
            ShotDecision(
                scene_id=scene_id,
                decision=decision,
                reason=reason.strip(),
                reviewer=reviewer or "anonymous",
            )
        )
        self.save()
        return shot

    # -- reads -------------------------------------------------------------
    def shots(self) -> list[StoryboardShot]:
        return sorted(self._shots.values(), key=lambda s: (s.index, s.scene_id))

    def get(self, scene_id: str) -> StoryboardShot | None:
        return self._shots.get(scene_id)

    def summary(self) -> dict[str, Any]:
        shots = self.shots()
        approved = [s for s in shots if s.status == SHOT_APPROVED]
        rejected = [s for s in shots if s.status == SHOT_REJECTED]
        pending = [s for s in shots if s.status == SHOT_PENDING]
        scored = [s for s in shots if (s.quality or {}).get("score") is not None]
        costs = {s.scene_id: s.cost_usd for s in shots}
        # 决定质量分的钱 vs 决定不做的钱
        approved_cost = round(sum(s.cost_usd for s in approved), 4)
        rejected_cost = round(sum(s.cost_usd for s in rejected), 4)
        return {
            "run_id": self.run_id,
            "total": len(shots),
            "approved": len(approved),
            "rejected": len(rejected),
            "pending": len(pending),
            "total_cost_usd": round(sum(s.cost_usd for s in shots), 4),
            "approved_cost_usd": approved_cost,
            "rejected_cost_usd": rejected_cost,
            "quality_scored": len(scored),
            "quality_unmeasured": len(shots) - len(scored),
            "mean_quality": (
                round(sum(float(s.quality["score"]) for s in scored) / len(scored), 4)
                if scored
                else None
            ),
            "gate": (
                "empty"
                if not shots
                else (
                    "awaiting_review"
                    if pending
                    else ("resolved_with_rejects" if rejected else "open")
                )
            ),
            "costs": costs,
        }

    def contact_sheet(self, *, output_path: str | Path | None = None) -> dict[str, Any]:
        """Compose the real PNG contact sheet of the shots that have a thumbnail."""
        from hevi.layer4_legacy.review.oprim_impl.frames import build_contact_sheet

        shots = [s for s in self.shots() if s.thumbnail and Path(s.thumbnail).is_file()]
        out = self.summary()
        out["sheet"] = None
        out["thumbnails"] = [
            {"scene_id": s.scene_id, "thumbnail": s.thumbnail, "status": s.status}
            for s in self.shots()
        ]
        if not shots:
            return out
        dest = Path(output_path) if output_path else self.dir / "contact_sheet.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            sheet = build_contact_sheet(
                frames=[Path(s.thumbnail) for s in shots],
                output_path=dest,
                labels=tuple(f"#{s.index} {s.scene_id} [{s.status}]" for s in shots),
                columns=min(4, len(shots)),
            )
        except Exception as exc:
            out["sheet_error"] = str(exc)
            return out
        out["sheet"] = {"path": str(dest), **sheet}
        return out

    def clear(self) -> None:
        """Drop the whole board (test / re-plan hygiene)."""
        self._shots.clear()
        if self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)


__all__ = [
    "SHOT_APPROVED",
    "SHOT_PENDING",
    "SHOT_REJECTED",
    "ShotDecision",
    "StoryboardBoard",
    "StoryboardShot",
    "measure_quality",
]
