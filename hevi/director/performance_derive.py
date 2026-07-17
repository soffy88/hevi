"""INC-002 v0.2 自动派生 —— 声音 / 遮挡 / 负面约束从 schema 确定性派生(零模型),+ 声音编译 + P8。

"比标尺高"的核心:标尺靠人手写声音、手记"不要多余手指";我们从 physiology/prop/body 自动派生
(§4.6.1 声音表、§5.5 负面表、§4.7 遮挡)。声画天然同步、零遗漏。全部纯函数、确定性、可测。
"""

from __future__ import annotations

from hevi.director.performance_track import PerformanceLintFinding
from hevi.director.pipeline_schemas import (
    AudioSegment,
    AudioTrack,
    LightingOcclusion,
    PerformancePhase,
    PerformanceTrack,
    ShotListItem,
)


def _fmt_s(v: float) -> str:
    return f"{v:g}"


def _dedup(seq: list[str]) -> list[str]:
    return list(dict.fromkeys(s for s in seq if s))


# ── §4.6.1 声音自动派生表(确定性)──────────────────────────────────────────────
_BREATH_SOUND = {
    "shallow_rapid": "急促的鼻息",
    "ragged": "破碎的呼吸",
    "deep": "一口长气从鼻腔呼出",
    "held": "",  # 屏息 → 静音
    "none": "",
}
# 有机械动作的接触态 + 金属 → 机械轻响(idle 态如 guard/face/threshold/holding 不发声)。
_MECH_STATES = {
    "pressure_building",
    "releasing",
    "lifted",
    "off",
    "drawing",
    "creeping",
    "released",
}


def derive_sounds_for_phase(phase: PerformancePhase) -> list[str]:
    """从一段表演的 physiology/body/prop 派生该段声音(§4.6.1)。声音是生理与物理的结果。"""
    sounds: list[str] = []
    fp = phase.facial_performance
    if fp:
        if fp.physiology.swallow:
            sounds.append("一次吞咽声(喉结滚动)")
        if fp.physiology.lip_state == "parting":
            sounds.append("嘴唇分开的轻微声")
    b = phase.body
    if b:
        sounds.append(_BREATH_SOUND.get(b.breath, ""))
        if b.tension == "collapsing":
            sounds.append("衣料摩擦、肩部松弛的窸窣声")
    for p in phase.prop_performance:
        if (p.material or "").lower() == "metal":
            if p.tremor.amplitude_mm:
                sounds.append("金属极微弱的震响")
            if p.grip.firmness:
                sounds.append("金属在掌心的轻微摩擦")
            if p.contact_state.state in _MECH_STATES:
                sounds.append("扳机护圈的机械轻响")
    return _dedup(sounds)


def derive_audio_track(
    track: PerformanceTrack | None, existing: AudioTrack | None = None
) -> AudioTrack | None:
    """从 performance_track 逐段派生 derived_sounds,建 audio_track。existing 的 manual_sounds/
    ambient/music/dialogue 尽量保留(按时间窗对齐合并)。空 track → None(inert)。"""
    if track is None or not track.phases:
        return existing
    out = AudioTrack(
        music=existing.music if existing else "",
        dialogue=existing.dialogue if existing else "",
        ambient=existing.ambient if existing else AudioTrack().ambient,
    )
    manual_by_window = {}
    for seg in existing.segments if existing else []:
        manual_by_window[(round(seg.t_start_s, 3), round(seg.t_end_s, 3))] = seg.manual_sounds
    for ph in sorted(track.phases, key=lambda p: (p.order, p.t_start_s)):
        key = (round(ph.t_start_s, 3), round(ph.t_end_s, 3))
        out.segments.append(
            AudioSegment(
                t_start_s=ph.t_start_s,
                t_end_s=ph.t_end_s,
                derived_sounds=derive_sounds_for_phase(ph),
                manual_sounds=manual_by_window.get(key, []),
            )
        )
    return out


# ── §4.7 遮挡自动派生(body.posture → occlusion)──────────────────────────────
_HEAD_DOWN_KW = ("低头", "低垂", "垂首", "俯", "埋头", "头垂", "垂头")


def derive_occlusion(body) -> LightingOcclusion | None:
    """姿态推导遮挡默认:低头 → 面部阴影加深(§4.7,LLM 未填时的候选)。无匹配 → None。"""
    if body and any(k in (body.posture or "") for k in _HEAD_DOWN_KW):
        return LightingOcclusion(cause="头部低垂", affected_area="面部", shadow_delta="deepen")
    return None


# ── §5.5 负面约束自动派生 ──────────────────────────────────────────────────────
def derive_negatives(shot: ShotListItem, *, photoreal: bool = True) -> list[str]:
    """从 schema 自动派生负面约束(§5.5)——有枪+手自动"不要多余手指/枪械变形",漏写不可能。
    无任何 INC-002 信号(performance_track/audio_track/manual_negatives)→ 返回 [],保持 inert
    (不给老镜头凭空加负面词、不改现有行为)。"""
    if not shot.performance_track and shot.audio_track is None and not shot.manual_negatives:
        return []
    neg: list[str] = ["不要字幕水印"]
    track = shot.performance_track
    phases = track.phases if track else []
    if any(pp.prop_type == "firearm" for ph in phases for pp in ph.prop_performance):
        neg += ["不要枪械结构变形", "不要多余或畸形的手指"]
    if any(ph.facial_performance and ph.facial_performance.muscle_actions for ph in phases):
        neg += ["不要脸部畸变", "确保符合解剖学的肌肉过渡"]
    if len(phases) > 1:
        neg.append("不要突然的表情跳变(相邻阶段须连续过渡)")
    if any(
        ph.facial_performance and ph.facial_performance.physiology.tear_state not in ("none", "")
        for ph in phases
    ):
        neg += ["眼泪须遵循重力与表面张力", "不要夸张哭泣"]
    at = shot.audio_track
    if at is not None:
        if not at.music:
            neg.append("不要背景音乐")
        if not at.dialogue:
            neg.append("不要台词/对白声")
    if photoreal:
        neg.append("不要卡通/动漫感")
    neg += shot.manual_negatives
    return _dedup(neg)


# ── §6 声音提示词编译(第四层)────────────────────────────────────────────────
_EVOLUTION_CN = {"constant": "持续", "fade_in": "渐显", "fade_out": "渐隐", "swell": "渐强"}


def compile_audio_prompt(audio_track: AudioTrack | None) -> str:
    """audio_track → 声音提示词(§6 第四层)。derived+manual 合并去重,逐段时间窗 + ambient。空→''。"""
    if audio_track is None:
        return ""
    lines: list[str] = []
    head = []
    if not audio_track.music:
        head.append("无配乐")
    if not audio_track.dialogue:
        head.append("无台词")
    if head:
        lines.append("(" + "、".join(head) + ")")
    for seg in sorted(audio_track.segments, key=lambda s: s.t_start_s):
        sounds = _dedup([*seg.derived_sounds, *seg.manual_sounds])
        if not sounds:
            continue
        line = f"[{_fmt_s(seg.t_start_s)}–{_fmt_s(seg.t_end_s)}s] " + "、".join(sounds)
        if seg.mix_note:
            line += f"({seg.mix_note})"
        lines.append(line)
    amb = audio_track.ambient
    if amb.bed:
        lines.append(f"环境声:{amb.bed}({_EVOLUTION_CN.get(amb.evolution, '')})")
    return "\n".join(lines)


# ── P8:声画咬合 —— 生理/道具事件必须有对应声音落在同一时间窗 ──────────────────
def lint_audio_sync(
    track: PerformanceTrack | None, audio_track: AudioTrack | None, *, shot_id: str = ""
) -> list[PerformanceLintFinding]:
    """P8:每个 physiology.swallow / prop.tremor 必须有对应声音落在同一时间窗(声画咬合,治
    "喉结滚动了但没吞咽声")。audio_track 缺失 → 不校验(未开声音层)。"""
    if track is None or audio_track is None:
        return []
    findings: list[PerformanceLintFinding] = []
    for ph in track.phases:
        needs: list[tuple[str, str]] = []
        fp = ph.facial_performance
        if fp and fp.physiology.swallow:
            needs.append(("喉结吞咽", "吞咽"))
        if any(p.tremor.amplitude_mm for p in ph.prop_performance):
            needs.append(("道具颤动", "震响"))
        for label, kw in needs:
            covered = any(
                seg.t_start_s < ph.t_end_s
                and seg.t_end_s > ph.t_start_s
                and any(kw in s for s in (*seg.derived_sounds, *seg.manual_sounds))
                for seg in audio_track.segments
            )
            if not covered:
                findings.append(
                    PerformanceLintFinding(
                        "P8",
                        shot_id,
                        [ph.phase_id],
                        f"{label}发生在 [{_fmt_s(ph.t_start_s)}–{_fmt_s(ph.t_end_s)}s] "
                        f"但同窗无对应声音(声画不咬合)",
                    )
                )
    return findings
