"""Demo: Applying Hevi's universal layout_gate to amtpl motion templates.

This script fulfills step 4 of BRANDFILM_TASK:
  "把 layout_audit 的逐帧文字越界、重叠检测抽成 Hevi 的通用闸门函数，至少给 amtpl 模板调用一次，做出示例。"

It demonstrates:
1. Running `audit_sampled_frames` on standard amtpl timeline frames (passing case).
2. Running `audit_sampled_frames` on a deliberate defect case (text collision + safe-area breach),
   verifying that the gate catches real text overlapping and border margin penetration.
"""

from __future__ import annotations

import json
from pathlib import Path

from hevi.validation.layout_gate import (
    Box,
    LayoutAuditReport,
    audit_sampled_frames,
)


def run_amtpl_gate_example(verbose: bool = True) -> tuple[LayoutAuditReport, LayoutAuditReport]:
    """Execute the layout gate audit on amtpl template scenarios."""
    canvas_w, canvas_h = 1080, 1920  # standard 9:16 portrait canvas

    # Scenario 1: Normal compliant amtpl timeline explainer playback
    # Two milestones appearing at different vertical intervals inside safe margins (> 48px).
    compliant_samples: dict[float, list[Box]] = {}
    for i in range(30):
        t = round(i * 0.1, 1)
        # Milestone 1: top title and subtitle
        m1_title = Box(x=80, y=120, w=400, h=44, text="2023 · 生成式视频元年", alpha=1.0)
        m1_sub = Box(x=80, y=180, w=600, h=32, text="扩散模型进入高分辨率运动生成阶段", alpha=1.0)
        # Milestone 2: lower card appears at t >= 1.5s
        boxes = [m1_title, m1_sub]
        if t >= 1.5:
            m2_title = Box(x=80, y=360, w=420, h=44, text="2024 · 物理引擎与长镜头统一", alpha=1.0)
            m2_sub = Box(x=80, y=420, w=640, h=32, text="多模态世界模型实现空间一致性推演", alpha=1.0)
            boxes.extend([m2_title, m2_sub])
        compliant_samples[t] = boxes

    report_compliant = audit_sampled_frames(
        compliant_samples,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        step=0.1,
        min_run=0.3,
        safe_margin=48.0,
        overlap_threshold=0.12,
    )

    # Scenario 2: Defect case (overlapping subtitles and edge bleeding)
    # Common amtpl failure: Subtitle 2 renders at the same vertical offset as Subtitle 1 (collision),
    # and a badge is placed inside the 48px margin (x=20, safe area breach).
    defect_samples: dict[float, list[Box]] = {}
    for i in range(30):
        t = round(i * 0.1, 1)
        # Defect 1: Safe-area breach (x=16 < 48px margin)
        badge = Box(x=16, y=60, w=180, h=36, text="[专题讲解]", alpha=1.0)
        # Defect 2: Text Collision (Line 1 and Line 2 occupy same space: y=200..250)
        line1 = Box(x=80, y=200, w=500, h=40, text="第一行讲解文本：全流程工业化调度", alpha=1.0)
        line2 = Box(x=90, y=210, w=480, h=40, text="第二行重叠文本：算力与模型协同编排", alpha=1.0)
        defect_samples[t] = [badge, line1, line2]

    report_defect = audit_sampled_frames(
        defect_samples,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        step=0.1,
        min_run=0.3,
        safe_margin=48.0,
        overlap_threshold=0.12,
    )

    if verbose:
        print("=== AM TPL LAYOUT GATE EXAMPLE REPORT ===")
        print(f"\n1. Compliant amtpl template run:")
        print(f"   Status: {'PASS' if report_compliant.passed else 'FAIL'}")
        print(f"   Problems count: {len(report_compliant.problems)}")
        print(f"   Breakdown: {json.dumps(report_compliant.summary()['breakdown'], ensure_ascii=False)}")

        print(f"\n2. Defective amtpl template run (text collision + margin breach):")
        print(f"   Status: {'PASS' if report_defect.passed else 'FAIL'}")
        print(f"   Problems count: {len(report_defect.problems)}")
        print(f"   Failed kinds: {report_defect.failed_kinds}")
        for p in report_defect.problems:
            print(f"     - [{p.kind.upper()}] {p.from_t:.1f}s-{p.to_t:.1f}s: {p.key} ({p.detail})")

    return report_compliant, report_defect


if __name__ == "__main__":
    rep_ok, rep_fail = run_amtpl_gate_example(verbose=True)
    assert rep_ok.passed is True, "Compliant run must pass"
    assert rep_fail.passed is False, "Defective run must fail"
    assert "text collision" in rep_fail.failed_kinds
    assert "safe area" in rep_fail.failed_kinds
    print("\n✓ Layout gate successfully demonstrated and verified against amtpl use cases.")
