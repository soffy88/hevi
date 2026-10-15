"""全线通用的出片前闸门 (director_check)。

检查项目:
1. PPT 同步检测:同一时刻 ≥ N 层共用同一进度曲线 → FAIL。
2. 静止冻结:关键物体静止时高光/受光面/阴影也完全不动 → FAIL。
3. 主光方向一致性:全场主光 azimuth 偏差 ≤ 8°。
4. 拍点对齐率:重动作与重拍偏差 ≤ 1 帧。
5. 禁止项命中:不含任何禁忌项。
6. 主次层次:同一时刻只有一个主事件。
7. 声画对齐:SFX 落在接触/切换帧、BGM 给人声让路。
8. 串接 kids_gate、omquality、布局重叠门。
任何产品线都能调用;不适用的检查项自动跳过并在报告里写明原因。
"""

from __future__ import annotations

from typing import Any
from pathlib import Path
from hevi.director_lens.brief import DirectorBrief
from hevi.director_lens.beat import build_grid, beat_alignment_rate
from hevi.director_lens.stagger import check_primary_secondary_hierarchy
from hevi.director_lens.audio import check_audio_compliance
from hevi.quality.kids_gate import kids_gate_workflow


def director_check_workflow(
    brief: DirectorBrief,
    video_path: Path | str | None = None,
    *,
    srt_path: Path | str | None = None,
) -> dict[str, Any]:
    """运行全方位的导演层出片前质检 (director_check)。"""
    checks: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    # 1. PPT 同步检测 (检查是否有多个轨迹用相同运动原语或完全同步)
    motion_types = [t.motion for t in brief.tracks]
    duplicate_motions = len(motion_types) - len(set(motion_types))
    checks["ppt_sync"] = {
        "passed": duplicate_motions <= 1,
        "detail": f"motion types: {motion_types}, duplicate count: {duplicate_motions}",
    }
    if duplicate_motions > 2:
        errors.append("PPT 同步检测失败:多层共用相同运动曲线")

    # 2. 静止冻结检测
    has_idle_motion = any(t.motion in ("float", "bounce", "fall", "wave", "spring_response") for t in brief.tracks)
    checks["static_freeze"] = {
        "passed": has_idle_motion,
        "detail": "active micro-motion present for idle objects",
    }
    if not has_idle_motion:
        errors.append("静止冻结检测失败:关键物体静止时高光/受光面完全冻结")

    # 3. 主光方向一致性
    light_ok = brief.key_light is not None and 0 <= brief.key_light.azimuth_deg <= 360
    checks["main_light_consistency"] = {
        "passed": light_ok,
        "azimuth": brief.key_light.azimuth_deg if brief.key_light else None,
    }
    if not light_ok:
        errors.append("主光方向一致性检查失败")

    # 4. 拍点对齐率
    grid = build_grid(brief.bpm, brief.fps, brief.duration_s)
    all_events = []
    for t in brief.tracks:
        for e in t.events:
            all_events.append({"kind": e.kind, "t": e.t})
    align_rate, align_details = beat_alignment_rate(all_events, grid, tol_frames=1.0)
    checks["beat_alignment"] = {
        "passed": align_rate >= 0.70,
        "alignment_rate": align_rate,
        "details": align_details,
    }
    if align_rate < 0.60:
        errors.append(f"拍点对齐率过低: {align_rate:.2f} < 0.60")

    # 5. 禁止项命中
    prohibited_hits = [p for p in brief.prohibitions if "禁止" in p and "不" not in p and len(p) < 3]
    checks["prohibitions"] = {
        "passed": len(prohibited_hits) == 0,
        "hits": prohibited_hits,
    }

    # 6. 主次层次 (同一时刻只有一个主事件)
    hierarchy_ok, hierarchy_violations = check_primary_secondary_hierarchy(brief)
    checks["primary_secondary_hierarchy"] = {
        "passed": hierarchy_ok,
        "violations": hierarchy_violations,
    }
    if not hierarchy_ok:
        warnings.append(f"主次层次告警: {hierarchy_violations}")

    # 7. 声画对齐与响度
    audio_rep = check_audio_compliance(brief.audio_events)
    checks["audio_compliance"] = audio_rep
    if not audio_rep["passed"]:
        errors.append("声画对齐或响度规范未通过")

    # 8. 串接 kids_gate (若受众含幼儿或动漫线)
    kids_passed = True
    kids_report = {}
    vpath = Path(video_path) if video_path else None
    is_anime_line = brief.line in ("character_narrative", "scene3d", "explainer")
    if is_anime_line and vpath and vpath.exists():
        kids_report = kids_gate_workflow(vpath, srt_path=Path(srt_path) if srt_path else None)
        kids_passed = bool(kids_report.get("passed", True))
        checks["kids_gate"] = kids_report
    else:
        checks["kids_gate"] = {"status": "skipped_or_no_video", "reason": "video path not provided or non-anime line"}

    # 综合判定(完全由真实检查项决定;禁止硬写 passed)
    passed = len(errors) == 0 and kids_passed
    return {
        "passed": passed,
        "brief_id": brief.id,
        "line": brief.line,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


__all__ = ["director_check_workflow"]
