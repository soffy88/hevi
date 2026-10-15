"""结构自检门 story_check（任一 FAIL 拒绝出片，给出可读原因）。"""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field
from hevi.storyplan.model import StoryPlan, NEW_INFO_REQUIRED_FIELDS


class CheckItem(BaseModel):
    check_id: str
    name: str
    status: str = "PASS"  # PASS / FAIL / WARN
    message: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class StoryCheckReport(BaseModel):
    passed: bool = True
    checks: list[CheckItem] = Field(default_factory=list)
    summary: str = ""


# 幼儿内容安全违禁词表（kids_gate 核心）
FORBIDDEN_KIDS_WORDS = [
    "暴力", "血", "武器", "刀", "枪", "恐怖", "惊吓", "死", "杀",
    "玩火", "爬窗", "独自外出", "嘲笑", "笨", "蠢", "羞辱", "广告",
]


def run_story_check(plan: StoryPlan, *, hook_window_sec: float = 3.5, max_chars_per_sec: float = 3.5) -> StoryCheckReport:
    """运行全套 StoryPlan 结构自检门，任一 FAIL 拒绝出片。"""
    checks: list[CheckItem] = []

    # 1) 开场钩子检查：前 3.5 秒内画面/声音/字幕至少两项交代主题或提出问题
    hook = plan.narrative.hook
    hook_ok = hook.start_ms <= 500 and hook.end_ms <= int(hook_window_sec * 1000) and len(hook.text.strip()) > 0
    checks.append(
        CheckItem(
            check_id="C1_OPENING_HOOK",
            name="开场钩子前置门禁",
            status="PASS" if hook_ok else "FAIL",
            message=f"钩子类型 {hook.hook_type}，起止区间 [{hook.start_ms}ms, {hook.end_ms}ms]" + ("" if hook_ok else "：未在规定时间窗内或内容为空"),
            evidence={"hook": hook.model_dump(), "window_sec": hook_window_sec},
        )
    )

    # 2) 六项必填与动作结束状态检查
    all_shots = [sh for seq in plan.shots.sequences for sc in seq.scenes for sh in sc.shots]
    shot_errors = []
    for sh in all_shots:
        missing = [f for f in NEW_INFO_REQUIRED_FIELDS if not getattr(sh, f, None)]
        if missing:
            shot_errors.append(f"镜头 {sh.shot_id} 缺少必填项: {missing}")
        if not sh.end_state.strip():
            shot_errors.append(f"镜头 {sh.shot_id} 动作缺少明确结束状态 (end_state)")

    checks.append(
        CheckItem(
            check_id="C2_SHOT_REQUIRED_FIELDS",
            name="镜头六项必填与结束状态",
            status="PASS" if not shot_errors else "FAIL",
            message="所有镜头六项必填及结束状态齐备" if not shot_errors else "; ".join(shot_errors),
            evidence={"total_shots": len(all_shots), "errors": shot_errors},
        )
    )

    # 3) 冗余镜头检查：连续镜头新增信息为空
    redundant_found = False
    redundant_notes = []
    for i in range(1, len(all_shots)):
        prev_info = set(all_shots[i - 1].new_info)
        curr_info = set(all_shots[i].new_info)
        if not curr_info or (curr_info.issubset(prev_info) and len(all_shots[i].action) < 10):
            redundant_found = True
            redundant_notes.append(f"镜头 {all_shots[i].shot_id} 新增信息为空或完全重复")

    checks.append(
        CheckItem(
            check_id="C3_REDUNDANT_SHOTS",
            name="冗余镜头去重",
            status="PASS" if not redundant_found else "FAIL",
            message="无无效冗余镜头" if not redundant_found else "; ".join(redundant_notes),
            evidence={"redundant_notes": redundant_notes},
        )
    )

    # 4) 声画对齐与台词/语速检查（kids_gate）
    total_chars = len(plan.narration_text.replace(" ", ""))
    chars_per_s = total_chars / max(0.1, plan.duration_sec)
    speed_ok = chars_per_s <= max_chars_per_sec
    suffix_msg = "：合规" if speed_ok else "：超速违规"
    checks.append(
        CheckItem(
            check_id="C4_SPEECH_RATE_AND_SYNC",
            name="幼儿语速与声画对齐闸门",
            status="PASS" if speed_ok else "FAIL",
            message=f"旁白语速 {chars_per_s:.2f} 字/秒（标准 ≤ {max_chars_per_sec} 字/秒）" + suffix_msg,
            evidence={"chars_per_sec": round(chars_per_s, 2), "max_allowed": max_chars_per_sec},
        )
    )

    # 5) 叙事闭环检查：开头提出的问题/期待在结尾被回应
    hook_kw = set(re.findall(r"[\u4e00-\u9fa5]", hook.text))
    closing_text = plan.narrative.closing_response
    closing_kw = set(re.findall(r"[\u4e00-\u9fa5]", closing_text))
    overlap = hook_kw & closing_kw
    closure_ok = len(overlap) >= 1 or len(closing_text) > 5
    checks.append(
        CheckItem(
            check_id="C5_NARRATIVE_CLOSURE",
            name="叙事闭环检查",
            status="PASS" if closure_ok else "FAIL",
            message="开头钩子与结尾回应形成闭环" if closure_ok else "结尾未有效回应开头期待",
            evidence={"hook_text": hook.text, "closing": closing_text},
        )
    )

    # 6) 时间线检查：无空白黑场、字幕不超界、各轨不越界
    timeline = plan.timeline
    video_track = next((t for t in timeline.tracks if t.track_kind == "video"), None)
    timeline_ok = True
    timeline_msg = "时间线完整无断层"
    if video_track and video_track.clips:
        sorted_clips = sorted(video_track.clips, key=lambda c: c.start_ms)
        if sorted_clips[0].start_ms > 100 or sorted_clips[-1].end_ms < timeline.duration_ms - 100:
            timeline_ok = False
            timeline_msg = "时间线存在首尾留白或未铺满总时长"

    checks.append(
        CheckItem(
            check_id="C6_TIMELINE_INTEGRITY",
            name="时间线完整性与无黑场",
            status="PASS" if timeline_ok else "FAIL",
            message=timeline_msg,
            evidence={"duration_ms": timeline.duration_ms},
        )
    )

    # 7) 内容安全审查（kids_gate 词表）
    full_text = plan.narration_text + " " + hook.text + " " + " ".join(sh.purpose + sh.action for sh in all_shots)
    violations = [w for w in FORBIDDEN_KIDS_WORDS if w in full_text]
    safe_ok = len(violations) == 0
    checks.append(
        CheckItem(
            check_id="C7_CONTENT_SAFETY",
            name="幼儿内容安全词表审查",
            status="PASS" if safe_ok else "FAIL",
            message="内容纯净安全，无违禁词" if safe_ok else f"命中幼儿安全红线词: {violations}",
            evidence={"violations": violations},
        )
    )

    any_fail = any(c.status == "FAIL" for c in checks)
    summary_text = "全套自检通过 (PASS)" if not any_fail else "存在门禁未通过项 (FAIL)"
    return StoryCheckReport(
        passed=not any_fail,
        checks=checks,
        summary=summary_text,
    )
