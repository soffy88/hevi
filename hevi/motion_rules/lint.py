"""Static storyboard / shot spec linting for Hevi motion rules.

Validates a shot spec against design redlines (red flags) and best practices (yellow flags).
Zero runtime/model cost (CPU-only, deterministic rule enforcement).
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Standard prohibited keywords normalized (lowercase without spaces/underscores/hyphens)
PROHIBITED_KEYWORD_PATTERNS = {
    "shockwave_rings": ["shockwave", "shockwaverings"],
    "particle_bursts": ["particleburst", "particlebursts", "particles"],
    "rgb_split": ["rgbsplit", "chromaticaberration"],
    "camera_shake": ["camerashake", "shakescreen"],
    "lens_flare": ["lensflare", "flare"],
    "neon_glow": ["neonglow", "neon", "glow"],
    "grid_floor": ["gridfloor"],
    "flashing_background": ["flashingbackground", "flashingbg", "flashbg"],
    "bouncy_easing": ["bouncyeasing", "bouncy", "bounce", "elasticeasing"],
}


def _normalize_token(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", text).lower()


@dataclass(frozen=True)
class Finding:
    code: str
    level: str  # "red" or "yellow"
    shot: int | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "shot": self.shot,
            "message": self.message,
        }


@dataclass
class LintReport:
    passed: bool
    red_count: int
    yellow_count: int
    findings: list[Finding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "red_count": self.red_count,
            "yellow_count": self.yellow_count,
            "findings": [f.to_dict() for f in self.findings],
        }

    def format_text(self) -> str:
        status_str = "PASS (合规)" if self.passed else "FAIL (红灯拦截)"
        lines = [
            f"=== Storyboard Lint Report: {status_str} ===",
            f"红灯(Red): {self.red_count} 项 | 黄灯(Yellow): {self.yellow_count} 项",
        ]
        if not self.findings:
            lines.append("全部检查项合规，未发现违规项。")
        else:
            for f in self.findings:
                shot_label = f"Shot {f.shot}" if f.shot is not None else "Spec 全局"
                tag = "[红灯 RED]" if f.level == "red" else "[黄灯 YEL]"
                lines.append(f"  {tag} [{f.code}] {shot_label}: {f.message}")
        return "\n".join(lines)


def lint_storyboard(
    spec: dict[str, Any],
    *,
    bpm_tolerance: float = 0.02,
    max_shot_dur: float = 8.0,
    beat_subdivision: float = 1.0,
) -> LintReport:
    """Lint a storyboard / shot spec dictionary against motion rules.

    Parameters:
    - spec: Dictionary containing shots[] and metadata.
    - bpm_tolerance: Maximum deviation in seconds to be considered on BPM grid (default 20ms).
    - max_shot_dur: Maximum allowed duration for a single shot in seconds (default 8.0s).
    - beat_subdivision: Grid division in beats (1.0 = quarter note, 0.5 = eighth note).
    """
    findings: list[Finding] = []

    global_bpm = float(spec.get("bpm", 120.0))
    shots = spec.get("shots", [])

    # 1. Spec-level Yellow Flag: Missing contact sheet check
    has_contact_sheet = (
        spec.get("has_contact_sheet")
        or spec.get("contact_sheet")
        or spec.get("probe_frames")
    )
    if not has_contact_sheet:
        findings.append(
            Finding(
                code="MISSING_CONTACT_SHEET",
                level="yellow",
                shot=None,
                message="未在全量渲染前生成接触样张（contact sheet / probe frames），可能导致重叠或拥挤无法预检。",
            )
        )

    # 2. Spec-level Yellow Flag: Loop first/last frame mismatch
    is_loop = bool(spec.get("is_loop") or spec.get("loop"))
    if is_loop:
        first_frame = spec.get("first_frame")
        last_frame = spec.get("last_frame")
        if first_frame is not None and last_frame is not None and first_frame != last_frame:
            findings.append(
                Finding(
                    code="LOOP_FRAME_MISMATCH",
                    level="yellow",
                    shot=None,
                    message=f"循环动效首尾帧不一致（first={first_frame}, last={last_frame}），循环播放时会产生跳跃或顿挫。",
                )
            )

    # 3. Per-shot inspections
    for idx, shot in enumerate(shots):
        shot_start = float(shot.get("start", 0.0))
        shot_dur = float(shot.get("dur", 0.0))
        bpm = float(shot.get("bpm", global_bpm))

        # Check: Single shot > 8s (Red Flag)
        if shot_dur > max_shot_dur:
            findings.append(
                Finding(
                    code="SHOT_DURATION_EXCEEDED",
                    level="red",
                    shot=idx,
                    message=f"单镜时长 {shot_dur:.2f}s 超过上限 {max_shot_dur:.2f}s，缺乏剪辑节奏与视觉变换。",
                )
            )

        # Check: Prohibited items hit (Red Flag)
        effects = shot.get("effects", [])
        if isinstance(effects, str):
            effects = [effects]
        easing = str(shot.get("easing", ""))
        transition = shot.get("transition", {})

        check_elements: list[str] = list(effects)
        if easing:
            check_elements.append(easing)
        if isinstance(transition, str):
            check_elements.append(transition)
        elif isinstance(transition, dict):
            if "type" in transition:
                check_elements.append(str(transition["type"]))

        for elem in check_elements:
            norm_elem = _normalize_token(str(elem))
            for ban_id, patterns in PROHIBITED_KEYWORD_PATTERNS.items():
                for pat in patterns:
                    if pat in norm_elem:
                        findings.append(
                            Finding(
                                code="PROHIBITED_ELEMENT",
                                level="red",
                                shot=idx,
                                message=f"命中禁项元素 '{elem}' (规则项: {ban_id})，严禁使用廉价模板特效。",
                            )
                        )
                        break

        # Check: Transition start not aligned to BPM grid (Red Flag)
        # Transition start is explicit in transition dict or default to shot start (if after start 0)
        trans_start: float | None = None
        if isinstance(transition, dict) and "start" in transition:
            trans_start = float(transition["start"])
        elif shot_start > 0.0:
            trans_start = shot_start

        if trans_start is not None and bpm > 0:
            beat_sec = (60.0 / bpm) * beat_subdivision
            nearest_k = round(trans_start / beat_sec)
            nearest_beat_time = nearest_k * beat_sec
            diff = abs(trans_start - nearest_beat_time)
            if diff > bpm_tolerance:
                findings.append(
                    Finding(
                        code="BPM_GRID_MISALIGNMENT",
                        level="red",
                        shot=idx,
                        message=(
                            f"转场起点 {trans_start:.3f}s 未对齐 BPM 网格 (BPM={bpm:.1f}, "
                            f"网格周期={beat_sec:.3f}s, 最近网格点={nearest_beat_time:.3f}s, 误差={diff:.3f}s > {bpm_tolerance}s)。"
                        ),
                    )
                )

        # Container morph timing extraction
        container = shot.get("container_morph") or shot.get("container") or {}
        c_morph_start = container.get("start") or container.get("morph_start") or container.get("in")
        c_next_morph = container.get("next_morph") or container.get("morph_end") or container.get("next_morph_start") or container.get("out")

        # Check texts inside this shot
        texts = shot.get("texts", [])
        for t_idx, t_item in enumerate(texts):
            text_str = str(t_item.get("text", ""))
            t_in = float(t_item.get("in", 0.0))
            t_out = float(t_item.get("out", shot_dur))

            # Check: On-screen text contains full stop / period (Red Flag)
            stripped_text = text_str.strip()
            if stripped_text.endswith("。") or stripped_text.endswith(".") or "。" in stripped_text:
                findings.append(
                    Finding(
                        code="TEXT_CONTAINS_PERIOD",
                        level="red",
                        shot=idx,
                        message=f"屏上文字 '{text_str}' 包含句号，违反极简字排规范（屏上文字句末不加标点）。",
                    )
                )

            # Check: Text enters before container starts morphing (Red Flag)
            if c_morph_start is not None:
                morph_start_f = float(c_morph_start)
                if t_in < morph_start_f:
                    findings.append(
                        Finding(
                            code="TEXT_BEFORE_CONTAINER_MORPH",
                            level="red",
                            shot=idx,
                            message=(
                                f"文字 '{text_str}' 入场时间 ({t_in:.2f}s) 早于容器形变开始时间 "
                                f"({morph_start_f:.2f}s)，会导致字面在未稳固骨架内被裁切挤压。"
                            ),
                        )
                    )

            # Check: Text leaves after container finishes or next morph starts (Red Flag)
            if c_next_morph is not None:
                next_morph_f = float(c_next_morph)
                if t_out > next_morph_f:
                    findings.append(
                        Finding(
                            code="TEXT_AFTER_CONTAINER_MORPH",
                            level="red",
                            shot=idx,
                            message=(
                                f"文字 '{text_str}' 离场时间 ({t_out:.2f}s) 晚于容器下一次形变开始时间 "
                                f"({next_morph_f:.2f}s)，会导致文字与新形变发生重叠穿帮。"
                            ),
                        )
                    )

    red_count = sum(1 for f in findings if f.level == "red")
    yellow_count = sum(1 for f in findings if f.level == "yellow")
    passed = red_count == 0

    return LintReport(
        passed=passed,
        red_count=red_count,
        yellow_count=yellow_count,
        findings=findings,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint storyboard / shot spec JSON against motion rules")
    parser.add_argument("spec_path", help="Path to storyboard / shot spec JSON file")
    parser.add_argument("--json", action="store_true", help="Output JSON format report")
    parser.add_argument("--bpm-tolerance", type=float, default=0.02, help="BPM grid tolerance in seconds")
    parser.add_argument("--max-shot-dur", type=float, default=8.0, help="Max single shot duration")
    args = parser.parse_args()

    spec_file = Path(args.spec_path)
    if not spec_file.exists():
        print(f"Error: file not found: {spec_file}")
        raise SystemExit(2)

    try:
        spec_data = json.loads(spec_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        raise SystemExit(2)

    report = lint_storyboard(
        spec_data,
        bpm_tolerance=args.bpm_tolerance,
        max_shot_dur=args.max_shot_dur,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.format_text())

    # Exit code: 1 if red findings, 0 if clean or yellow only
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
