"""成片 cut 边界自检（对标 video-use self-eval）。

在展示给用户前检查：
  - EDL 硬规则
  - 成片时长 ≈ EDL 合计
  - cut 边界可探测（ffprobe + 可选 timeline 抽帧）
  - 字幕文件非空（若声明需要字幕）
  - 自检轮数上限
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.assembly.edit_craft import (
    SELF_EVAL_MAX_PASSES,
    EditCraftError,
    EditDecisionList,
    compute_output_duration,
    validate_edl,
)

logger = logging.getLogger(__name__)


@dataclass
class SelfEvalIssue:
    code: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class SelfEvalReport:
    passed: bool
    issues: list[SelfEvalIssue] = field(default_factory=list)
    warnings: list[SelfEvalIssue] = field(default_factory=list)
    cut_count: int = 0
    expected_duration_s: float = 0.0
    actual_duration_s: float | None = None
    pass_index: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": [
                {"code": i.code, "message": i.message, "severity": i.severity}
                for i in self.issues
            ],
            "warnings": [
                {"code": w.code, "message": w.message, "severity": w.severity}
                for w in self.warnings
            ],
            "cut_count": self.cut_count,
            "expected_duration_s": self.expected_duration_s,
            "actual_duration_s": self.actual_duration_s,
            "pass_index": self.pass_index,
        }


def probe_duration_s(path: Path) -> float | None:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        return float(proc.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def extract_cut_boundary_frame(
    video: Path,
    t: float,
    output: Path,
    *,
    window_s: float = 0.05,
) -> Path | None:
    """在 cut 边界附近抽一帧，供人工/视觉复查。失败返回 None。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    ts = max(0.0, t + window_s)
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(output),
            ],
            capture_output=True,
            timeout=60,
        )
        if proc.returncode == 0 and output.exists():
            return output
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("extract cut frame failed at t=%.3f", t)
    return None


def self_eval_edl(
    edl: EditDecisionList | dict,
    *,
    final_path: Path | None = None,
    require_confirm: bool = True,
    require_subtitles: bool = False,
    pass_index: int = 1,
    extract_boundary_frames: bool = False,
    verify_dir: Path | None = None,
    duration_tolerance_s: float = 0.35,
) -> SelfEvalReport:
    """对 EDL + 可选成片做自检。不抛异常（除非 EDL 结构致命）；用 report.passed。"""
    if isinstance(edl, dict):
        edl = EditDecisionList.from_dict(edl)

    issues: list[SelfEvalIssue] = []
    warnings: list[SelfEvalIssue] = []

    if pass_index > SELF_EVAL_MAX_PASSES:
        issues.append(
            SelfEvalIssue(
                code="max_passes",
                message=f"自检已超过 {SELF_EVAL_MAX_PASSES} 轮，停止自动修复，交人工",
            )
        )
        return SelfEvalReport(
            passed=False,
            issues=issues,
            cut_count=max(0, len(edl.ranges) - 1),
            pass_index=pass_index,
        )

    try:
        edl_warnings = validate_edl(edl, require_confirm=require_confirm)
        for w in edl_warnings:
            warnings.append(SelfEvalIssue(code="edl_warning", message=w, severity="warning"))
    except EditCraftError as e:
        issues.append(SelfEvalIssue(code="edl_invalid", message=str(e)))
        return SelfEvalReport(
            passed=False,
            issues=issues,
            warnings=warnings,
            cut_count=max(0, len(edl.ranges) - 1),
            pass_index=pass_index,
        )

    expected = compute_output_duration(edl.ranges)
    actual: float | None = None

    if final_path is not None:
        if not final_path.exists():
            issues.append(
                SelfEvalIssue(code="missing_final", message=f"成片不存在: {final_path}")
            )
        else:
            if final_path.stat().st_size < 1024:
                issues.append(
                    SelfEvalIssue(code="tiny_final", message="成片文件过小，可能损坏")
                )
            actual = probe_duration_s(final_path)
            if actual is None:
                warnings.append(
                    SelfEvalIssue(
                        code="probe_failed",
                        message="ffprobe 无法读取成片时长",
                        severity="warning",
                    )
                )
            elif abs(actual - expected) > duration_tolerance_s:
                issues.append(
                    SelfEvalIssue(
                        code="duration_mismatch",
                        message=(
                            f"成片时长 {actual:.3f}s 与 EDL 合计 {expected:.3f}s "
                            f"偏差 > {duration_tolerance_s}s"
                        ),
                    )
                )

            if extract_boundary_frames and verify_dir is not None and len(edl.ranges) > 1:
                verify_dir.mkdir(parents=True, exist_ok=True)
                # 累计 cut 时间点
                t = 0.0
                for i, r in enumerate(edl.ranges[:-1]):
                    t += r.duration()
                    extract_cut_boundary_frame(
                        final_path, t, verify_dir / f"cut_{i:02d}_{t:.2f}s.jpg"
                    )

    if require_subtitles:
        sub = edl.subtitles
        if not sub:
            issues.append(
                SelfEvalIssue(code="no_subtitles", message="要求字幕但 EDL.subtitles 为空")
            )
        else:
            sp = Path(sub)
            if not sp.exists() or sp.stat().st_size == 0:
                issues.append(
                    SelfEvalIssue(code="empty_subtitles", message=f"字幕文件缺失或为空: {sp}")
                )

    # 规则：每段必须有 reason（剪辑可追溯）— 警告级
    for i, r in enumerate(edl.ranges):
        if not (r.reason or r.quote or r.beat):
            warnings.append(
                SelfEvalIssue(
                    code="missing_rationale",
                    message=f"ranges[{i}] 缺少 beat/quote/reason，不利于追溯",
                    severity="warning",
                )
            )

    passed = len(issues) == 0
    return SelfEvalReport(
        passed=passed,
        issues=issues,
        warnings=warnings,
        cut_count=max(0, len(edl.ranges) - 1),
        expected_duration_s=expected,
        actual_duration_s=actual,
        pass_index=pass_index,
    )


def assert_self_eval_passed(report: SelfEvalReport) -> None:
    """硬门：自检不过则拒绝归档。"""
    if not report.passed:
        detail = "; ".join(f"{i.code}: {i.message}" for i in report.issues)
        raise EditCraftError(f"成片自检未通过，禁止归档: {detail}")
