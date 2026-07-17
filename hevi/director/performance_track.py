"""INC-002 单镜表演密度层 —— performance_track 的编译器与确定性校验(第一批)。

- compile_temporal_prompt:把 PerformanceTrack 编译成"时序提示词"(逐段时间窗的自然语言),
  拼在基础提示词之后(见 INC-002 §6)。模型认自然语言,不认结构化枚举,故这里把枚举翻成中文。
- lint_performance_track:零模型成本的确定性 lint。第一批落 P1(时间轴连续无缝隙/无重叠/
  总和=total_duration_s)与 P5(eyeline 状态转移合法性)。P2/P3/P4/P6 随第二三批加。

标尺是一份散文 prompt——"可校验"正是我们比它高的地方:这里把时间轴断裂、视线瞬移在编译前拦下。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from hevi.director.pipeline_schemas import (
    FacialPerformance,
    PerformancePhase,
    PerformanceTrack,
)

# ── 枚举 → 中文(编译进 prompt 用;未知值原样透出,不丢信息)────────────────────
_EYELINE_STATE_CN = {
    "locked": "视线锁定",
    "breaking": "视线开始游离",
    "averted": "视线回避移开",
    "returning": "视线重新回视",
    "closed": "双眼闭合",
}
_DIR_CN = {
    "center": "正前方",
    "down": "下方",
    "down_left": "左下方",
    "down_right": "右下方",
    "up": "上方",
    "up_left": "左上方",
    "up_right": "右上方",
    "left": "左侧",
    "right": "右侧",
}
_SPEED_CN = {"snap": "骤然", "quick": "快速", "slow": "缓慢", "trembling": "颤动着"}
_TENSION_CN = {
    "rigid": "僵直",
    "taut": "绷紧",
    "trembling": "颤抖",
    "slack": "松弛",
    "collapsing": "垮塌",
}
_BREATH_CN = {
    "held": "屏息",
    "shallow_rapid": "急促浅促",
    "ragged": "参差不匀",
    "deep": "深长",
    "none": "",
}
# ── INC-002 第二批:面部生理层枚举 → 中文 ──
_TEAR_CN = {
    "none": "",
    "welling": "泪水在眼眶堆积",
    "film": "泪膜浮起蒙住眼",
    "brimming": "泪水将溢未溢",
    "falling": "泪水滑落",
    "dried": "泪痕已干",
}
_VASC_CN = {"clear": "", "faint": "眼白微泛红丝", "congested": "眼白充血泛红"}
_BLINK_CN = {
    "none": "凝住不眨眼",
    "normal": "",
    "rapid": "急促眨眼",
    "forced_open": "强撑着睁大不闭",
    "closing": "眼睑缓缓合下",
}
_LIP_CN = {
    "pressed": "嘴唇紧抿",
    "parting": "嘴唇微张",
    "trembling": "嘴唇颤抖",
    "slack": "嘴唇松弛",
}
_FLUSH_CN = {"none": "", "cheeks": "双颊泛红", "neck": "脖颈泛红"}
_SWEAT_CN = {"none": "", "sheen": "薄薄一层汗光", "beads": "渗出汗珠"}
_PORES_CN = {"visible": "毛孔可见", "subtle": "毛孔隐约", "none": ""}
_SKIN_QUALITY_CN = {
    "natural_imperfect": "自然微瑕的真实肤质",
    "clean": "干净肤质",
    "weathered": "风霜粗糙肤质",
}
# P3:泪水单调演化的等级(none→welling→film→brimming→falling→dried,不可跳跃/倒流)。
_TEAR_RANK = {"none": 0, "welling": 1, "film": 2, "brimming": 3, "falling": 4, "dried": 5}


def _cn(mapping: dict[str, str], key: str) -> str:
    """枚举翻中文;空/未知原样返回(不丢信息)。"""
    key = (key or "").strip()
    return mapping.get(key, key)


def _fmt_s(v: float) -> str:
    """3.0 → '3',3.5 → '3.5'(时间戳好读)。"""
    return f"{v:g}"


def _compile_facial(fp: FacialPerformance | None) -> str:
    """FacialPerformance → 面部表演自然语言。muscle_actions **只输出 visible_result**(模型认
    "眉头紧皱"不认"降眉肌",muscle 名留给 debug_context/verdict);未填 → 空串(inert,降级为
    emotional_state 自然语言)。"""
    if fp is None:
        return ""
    bits: list[str] = []
    bits.extend(m.visible_result.strip() for m in fp.muscle_actions if m.visible_result.strip())

    phy = fp.physiology
    if phy:
        tear = _cn(_TEAR_CN, phy.tear_state)
        if tear:
            td = phy.tear_detail
            if td and td.side in ("left", "right"):
                tear = ("左" if td.side == "left" else "右") + "眼" + tear
            bits.append(tear)
        vasc = _cn(_VASC_CN, phy.eye_vasculature)
        if vasc:
            bits.append(vasc)
        if phy.pupil and phy.pupil.dilation:
            pup = f"瞳孔放大{_fmt_s(phy.pupil.dilation)}"
            if phy.pupil.movement:
                pup += f"、{phy.pupil.movement}"
            bits.append(pup)
        blink = _cn(_BLINK_CN, phy.blink)
        if blink:
            bits.append(blink)
        if phy.swallow:
            bits.append((phy.swallow_difficulty or "") + "吞咽,喉结滚动")
        lip = _cn(_LIP_CN, phy.lip_state)
        if lip:
            bits.append(lip)
        flush = _cn(_FLUSH_CN, phy.skin_flush)
        if flush:
            bits.append(flush)

    sk = fp.skin_texture
    if sk:
        bits.extend(
            cn
            for cn in (
                _cn(_SKIN_QUALITY_CN, sk.quality),
                _cn(_PORES_CN, sk.pores),
                _cn(_SWEAT_CN, sk.sweat),
            )
            if cn
        )
        bits.extend(b.strip() for b in sk.blemishes if b.strip())
        if sk.lip_texture:
            bits.append(sk.lip_texture)
        if sk.preserve_base_tone:
            bits.append("保留原本面部底色不掩盖")

    return "面部:" + "、".join(bits) if bits else ""


def _compile_phase(ph: PerformancePhase) -> str:
    head = f"[{_fmt_s(ph.t_start_s)}–{_fmt_s(ph.t_end_s)}s]"
    if ph.label:
        head += f" {ph.label}"

    parts: list[str] = []

    el = ph.eyeline_track
    if el and (el.state or el.direction or el.target_ref):
        eye = _cn(_EYELINE_STATE_CN, el.state) or "视线"
        if el.direction and el.state != "closed":
            eye += f",朝{_cn(_DIR_CN, el.direction)}"
        if el.target_ref:
            eye += f",看向{el.target_ref}"
        speed = _cn(_SPEED_CN, el.transition_speed)
        if speed and speed != "缓慢":
            eye += f"({speed})"
        parts.append(eye)

    em = ph.emotional_state
    if em and em.primary:
        emo = f"情绪:{em.primary}"
        if em.intensity:
            emo += f"(强度{_fmt_s(em.intensity)})"
        if em.conflict_with:
            emo += f",与「{em.conflict_with}」交战"
        parts.append(emo)

    b = ph.body
    if b:
        bits = []
        if b.posture:
            bits.append(b.posture)
        tension = _cn(_TENSION_CN, b.tension)
        if tension:
            bits.append(f"身体{tension}")
        breath = _cn(_BREATH_CN, b.breath)
        if breath:
            bits.append(f"呼吸{breath}")
        if bits:
            parts.append("、".join(bits))

    facial = _compile_facial(ph.facial_performance)
    if facial:
        parts.append(facial)

    return head + " → " + ";".join(parts) if parts else head


def compile_temporal_prompt(track: PerformanceTrack | None) -> str:
    """PerformanceTrack → 时序提示词(逐段时间窗自然语言)。空 → 空串(inert,拼接方无副作用)。"""
    if track is None or not track.phases:
        return ""
    phases = sorted(track.phases, key=lambda p: (p.order, p.t_start_s))
    return "\n".join(_compile_phase(ph) for ph in phases)


# ── 确定性 lint(零模型成本)──────────────────────────────────────────────────


@dataclass
class PerformanceLintFinding:
    rule: str  # P1/P5
    shot_id: str
    phase_ids: list[str]
    message: str
    severity: str = "warn"


# P5:eyeline 状态"自然演化"的合法相邻(非 snap 时必须相邻推进,不许跳变)。
# 闭眼可从任意态进入(闭上眼),睁眼(closed→任意)也允许。
_EYELINE_NEXT_OK: dict[str, set[str]] = {
    "locked": {"locked", "breaking", "closed"},
    "breaking": {"breaking", "averted", "returning", "closed"},
    "averted": {"averted", "returning", "closed"},
    "returning": {"returning", "locked", "breaking", "closed"},
    "closed": {"closed", "locked", "breaking", "averted", "returning"},
}
_EPS = 1e-6


def lint_performance_track(
    track: PerformanceTrack | None, *, shot_id: str = ""
) -> list[PerformanceLintFinding]:
    """P1(时间轴连续)+ P5(视线转移合法)。空 track → 无 finding。"""
    if track is None or not track.phases:
        return []
    findings: list[PerformanceLintFinding] = []
    phases = sorted(track.phases, key=lambda p: (p.order, p.t_start_s))

    # ── P1:时间窗连续无缝隙、无重叠、每段正时长、首=0、末=total_duration_s ──
    findings.extend(
        PerformanceLintFinding(
            "P1",
            shot_id,
            [ph.phase_id],
            f"阶段 {ph.phase_id or ph.order} 时长非正:{_fmt_s(ph.t_start_s)}→{_fmt_s(ph.t_end_s)}",
        )
        for ph in phases
        if ph.t_end_s - ph.t_start_s <= _EPS
    )
    if phases[0].t_start_s > _EPS:
        findings.append(
            PerformanceLintFinding(
                "P1",
                shot_id,
                [phases[0].phase_id],
                f"首段未从 0 起(={_fmt_s(phases[0].t_start_s)})",
            )
        )
    for a, b in pairwise(phases):
        gap = b.t_start_s - a.t_end_s
        if abs(gap) > _EPS:
            kind = "缝隙" if gap > 0 else "重叠"
            findings.append(
                PerformanceLintFinding(
                    "P1",
                    shot_id,
                    [a.phase_id, b.phase_id],
                    f"阶段 {a.phase_id or a.order}→{b.phase_id or b.order} 时间轴{kind}:"
                    f"{_fmt_s(a.t_end_s)} vs {_fmt_s(b.t_start_s)}",
                )
            )
    if track.total_duration_s and abs(phases[-1].t_end_s - track.total_duration_s) > _EPS:
        findings.append(
            PerformanceLintFinding(
                "P1",
                shot_id,
                [phases[-1].phase_id],
                f"末段结束 {_fmt_s(phases[-1].t_end_s)}s ≠ total_duration_s "
                f"{_fmt_s(track.total_duration_s)}s",
            )
        )

    # ── P5:eyeline 状态转移合法性(跳变须 transition_speed=snap)──
    for a, b in pairwise(phases):
        sa = (a.eyeline_track.state or "").strip()
        sb = (b.eyeline_track.state or "").strip()
        if not sa or not sb or sa not in _EYELINE_NEXT_OK:
            continue
        if sb not in _EYELINE_NEXT_OK[sa] and b.eyeline_track.transition_speed != "snap":
            findings.append(
                PerformanceLintFinding(
                    "P5",
                    shot_id,
                    [a.phase_id, b.phase_id],
                    f"视线状态跳变 {sa}→{sb}(非相邻演化),须 transition_speed=snap 才允许",
                )
            )

    # ── P3(第二批):tear_state 单调演化——不可倒流、不可跳跃(相邻段 rank 差只能 0 或 +1)──
    for a, b in pairwise(phases):
        fa = a.facial_performance
        fb = b.facial_performance
        if fa is None or fb is None:
            continue
        ra = _TEAR_RANK.get(fa.physiology.tear_state)
        rb = _TEAR_RANK.get(fb.physiology.tear_state)
        if ra is None or rb is None:
            continue
        if rb < ra:
            findings.append(
                PerformanceLintFinding(
                    "P3",
                    shot_id,
                    [a.phase_id, b.phase_id],
                    f"泪水倒流 {fa.physiology.tear_state}→{fb.physiology.tear_state}(不可逆演化)",
                )
            )
        elif rb - ra > 1:
            findings.append(
                PerformanceLintFinding(
                    "P3",
                    shot_id,
                    [a.phase_id, b.phase_id],
                    f"泪水跳跃 {fa.physiology.tear_state}→{fb.physiology.tear_state}(须逐级演化)",
                )
            )
    return findings
