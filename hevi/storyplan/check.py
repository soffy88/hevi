"""结构自检门 story_check（任一 FAIL 拒绝出片，给出可读原因）。"""

from __future__ import annotations

__all__ = ["run_story_check", "CheckItem", "StoryCheckReport", "FORBIDDEN_KIDS_WORDS"]

import re
from typing import Any
from pydantic import BaseModel, Field
from hevi.storyplan.model import StoryPlan, NEW_INFO_REQUIRED_FIELDS
from hevi.quality.kids_gate import FORBIDDEN_WORDS
import jieba


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


# 幼儿内容安全违禁词表单一来源：hevi.quality.kids_gate.FORBIDDEN_WORDS
# （由 hevi/kids/data/kids_safety_rules.json 的 categories 扁平化而来）。
# 此处只保留旧名别名供既有导入兼容，不再自备词表独立维护
# （先例：hevi/kids/story_gate.py 同样直接复用 FORBIDDEN_WORDS）。
FORBIDDEN_KIDS_WORDS = FORBIDDEN_WORDS


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

    # 5) 叙事闭环检查（FIX-1）：必须显式回应 hook（词语级 jieba 交集或 beat expectation 重叠），删除纯 len>5 兜底
    hook_words = set(jieba.lcut(hook.text)) - {"", " ", "？", "？", "呢", "吗", "的", "了", "啊", "什么", "怎么", "呢"}
    closing_text = plan.narrative.closing_response
    closing_words = set(jieba.lcut(closing_text)) - {"", " ", "？", "？", "呢", "吗", "的", "了", "啊", "好", "吧"}
    beat_words = set()
    for b in plan.narrative.beats:
        beat_words.update(jieba.lcut(b.expectation))

    overlap = (hook_words & closing_words) or (beat_words & closing_words)
    closure_ok = len(overlap) >= 1 and len(closing_text.strip()) > 2
    checks.append(
        CheckItem(
            check_id="C5_NARRATIVE_CLOSURE",
            name="叙事闭环检查",
            status="PASS" if closure_ok else "FAIL",
            message="开头钩子与结尾回应形成语义闭环" if closure_ok else "结尾未有效回应开头期待或缺乏关键词交集",
            evidence={"hook_text": hook.text, "closing": closing_text, "overlap": list(overlap)},
        )
    )

    # 6) 时间线检查（FIX-2）：无空白黑场、字幕不超界、各轨不越界、空时间线拒绝
    timeline = plan.timeline
    video_track = next((t for t in timeline.tracks if t.track_kind == "video"), None)
    voice_tracks = [t for t in timeline.tracks if t.track_kind == "voice"]
    subtitle_tracks = [t for t in timeline.tracks if t.track_kind == "subtitle"]

    timeline_ok = True
    timeline_msg = "时间线完整无断层"

    if not timeline.tracks or not video_track or not video_track.clips:
        timeline_ok = False
        timeline_msg = "时间线缺失视频轨或为空"
    else:
        # Check all clips bounds against timeline duration and non-negative
        for track in timeline.tracks:
            for clip in track.clips:
                if clip.start_ms < 0 or clip.end_ms > timeline.duration_ms or clip.start_ms >= clip.end_ms:
                    timeline_ok = False
                    timeline_msg = f"轨道 {track.track_kind} 存在越界或无效 clip [{clip.start_ms}, {clip.end_ms}] (总时长 {timeline.duration_ms})"
                    break
            if not timeline_ok:
                break

        # Check subtitle coverage by voice clips
        if timeline_ok and subtitle_tracks and voice_tracks:
            voice_intervals = [(c.start_ms, c.end_ms) for vt in voice_tracks for c in vt.clips]
            for st in subtitle_tracks:
                for sc in st.clips:
                    covered = any(v[0] <= sc.start_ms + 150 and v[1] >= sc.end_ms - 150 for v in voice_intervals)
                    if not covered:
                        timeline_ok = False
                        timeline_msg = f"字幕片段 {sc.clip_id} [{sc.start_ms}, {sc.end_ms}] 超出语音区间范围"
                        break
                if not timeline_ok:
                    break

        # Check video head/tail gaps
        if timeline_ok and video_track and video_track.clips:
            sorted_clips = sorted(video_track.clips, key=lambda c: c.start_ms)
            if sorted_clips[0].start_ms > 100 or sorted_clips[-1].end_ms < timeline.duration_ms - 100:
                timeline_ok = False
                timeline_msg = "视频时间线存在首尾留白或未铺满总时长"

    checks.append(
        CheckItem(
            check_id="C6_TIMELINE_INTEGRITY",
            name="时间线完整性与无黑场",
            status="PASS" if timeline_ok else "FAIL",
            message=timeline_msg,
            evidence={"duration_ms": timeline.duration_ms, "tracks_count": len(timeline.tracks)},
        )
    )

    # 7) 内容安全审查（FIX-3：kids_gate 词表全覆盖）
    full_text = plan.narration_text + " " + hook.text + " " + " ".join(sh.purpose + sh.action + sh.end_state for sh in all_shots)
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

    # 8) 反应环检查（C8，WARN 级）：叙事四环 cause→process→result→reaction。
    # 含 result 拍时，其后（结尾收束前）应出现 reaction 拍——角色对结果的
    # 情绪/行为反应（对应 cinematic shot_intelligence 的 close_reaction 词条，
    # 此前无人强制调用）。缺失只报 WARN 不设 hard fail，避免打爆存量计划
    # （如 kids 六拍 greeting→problem→attempt→solution→recap→farewell，
    # 其中 recap 是复述而非反应，同样只会得到 WARN）。
    beats = plan.narrative.beats
    result_idx = next((i for i, b in enumerate(beats) if b.phase == "result"), None)
    reaction_idx = next((i for i, b in enumerate(beats) if b.phase == "reaction"), None)
    if result_idx is None:
        reaction_status = "PASS"
        reaction_msg = "无 result 拍，反应环检查不适用"
    elif reaction_idx is not None and reaction_idx > result_idx:
        reaction_status = "PASS"
        reaction_msg = "result 后存在 reaction 反应拍，叙事四环完整"
    elif reaction_idx is not None:
        reaction_status = "WARN"
        reaction_msg = "reaction 反应拍出现在 result 之前，未形成对结果的反应"
    else:
        reaction_status = "WARN"
        reaction_msg = "含 result 拍但其后缺少 reaction 反应拍（角色对结果的情绪/行为反应），叙事四环缺反应环"
    checks.append(
        CheckItem(
            check_id="C8_REACTION_BEAT",
            name="叙事反应环检查",
            status=reaction_status,
            message=reaction_msg,
            evidence={
                "result_beat_index": result_idx,
                "reaction_beat_index": reaction_idx,
                "beat_phases": [b.phase for b in beats],
            },
        )
    )

    # 9) 跨镜动作衔接检查（C9，WARN 级）：下一镜 start_state 应与上一镜
    # end_state 一致（仅同场景内、且两者都显式声明时比对）。
    # 比对逻辑等价轻量实现自 hevi/prompt/continuity/validator.py
    # validate_film() 检查项 4（跨镜 start_state vs 上一镜 end_state，
    # strip 后逐字相等）；此处不改 validator 的公开行为，仅在 StoryPlan
    # 层落地。场景切换处状态本可重置，故跨 scene 不比对。
    continuity_notes: list[str] = []
    prev_shot = None
    for sh in all_shots:
        if prev_shot is not None and sh.scene_id == prev_shot.scene_id:
            prev_end = prev_shot.end_state.strip()
            curr_start = sh.start_state.strip()
            if prev_end and curr_start and prev_end != curr_start:
                continuity_notes.append(
                    f"镜头 {sh.shot_id} start_state 与上一镜 {prev_shot.shot_id} end_state 不一致"
                )
        prev_shot = sh
    checks.append(
        CheckItem(
            check_id="C9_ACTION_CONTINUITY",
            name="跨镜动作衔接检查",
            status="PASS" if not continuity_notes else "WARN",
            message="跨镜状态衔接一致" if not continuity_notes else "; ".join(continuity_notes),
            evidence={"continuity_notes": continuity_notes},
        )
    )

    any_fail = any(c.status == "FAIL" for c in checks)
    summary_text = "全套自检通过 (PASS)" if not any_fail else "存在门禁未通过项 (FAIL)"
    return StoryCheckReport(
        passed=not any_fail,
        checks=checks,
        summary=summary_text,
    )
