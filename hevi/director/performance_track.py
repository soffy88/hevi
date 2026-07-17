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
    CameraCurve,
    FacialPerformance,
    MuscleAction,
    PerformancePhase,
    PerformancePreset,
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
# ── INC-002 第三批:运镜曲线枚举 → 中文 ──
_EASING_CN = {"linear": "匀速", "ease_in": "渐入", "ease_out": "渐出", "accelerate": "加速"}
_MOVEMENT_CN = {
    "static": "",
    "push_in": "推近",
    "pull_out": "拉远",
    "pan": "横摇",
    "tilt": "纵摇",
    "follow": "跟拍",
}
_STRICTNESS_CN = {"absolute": "死锁", "soft": "软锁", "rack": "变焦点"}
_SYNC_CN = {
    "none": "",
    "character_breath": "与人物呼吸同步",
    "emotional_intensity": "随情绪强度起伏",
}
# ── INC-002 v0.2:道具/光 枚举 → 中文 ──
_CONTACT_STATE_CN = {
    # 枪械
    "guard": "手指搭在扳机护圈",
    "face": "手指滑上扳机面",
    "pressure_building": "施加初始压力",
    "threshold": "压力停在临界(将扣未扣)",
    "releasing": "压力减轻",
    "lifted": "手指抬起悬停",
    "off": "手指松开搭回护圈",
    # 弓箭
    "nocked": "箭已搭弦",
    "drawing": "拉弦中",
    "full_draw": "满弓",
    "holding": "满弓停住",
    "creeping": "走弦",
    "released": "撒放",
    "slack": "松弦",
}
_SHADOW_DELTA_CN = {"deepen": "阴影加深", "lighten": "阴影变浅", "shift": "阴影移动"}
_PATTERN_CN = {
    "rembrandt": "伦勃朗光",
    "split": "分割光",
    "rim": "轮廓光",
    "top": "顶光",
    "practical_bare_bulb": "裸灯泡硬光",
}
# P7:道具接触状态机的合法转移图(按 prop_type 分组;不在图内的 prop_type 不校验)。
_PROP_STATE_GRAPH: dict[str, dict[str, set[str]]] = {
    "firearm": {
        "guard": {"guard", "face"},
        "face": {"face", "pressure_building", "guard"},
        "pressure_building": {"pressure_building", "threshold", "releasing"},
        "threshold": {"threshold", "releasing"},
        "releasing": {"releasing", "lifted", "face"},
        "lifted": {"lifted", "off", "face"},
        "off": {"off", "guard"},
    },
    "bow": {
        "nocked": {"nocked", "drawing"},
        "drawing": {"drawing", "full_draw"},
        "full_draw": {"full_draw", "holding", "released"},
        "holding": {"holding", "creeping", "released"},
        "creeping": {"creeping", "released", "full_draw"},
        "released": {"released", "slack"},
        "slack": {"slack", "nocked"},
    },
}


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


def _compile_camera(cc: CameraCurve | None) -> str:
    """CameraCurve → 运镜自然语言(晃动频率曲线/焦点锁死度/推拉/镜头呼吸)。未填 → 空串(inert)。"""
    if cc is None:
        return ""
    bits: list[str] = []

    hh = cc.handheld
    if hh and hh.enabled:
        s = f"手持晃动 频率{_fmt_s(hh.frequency_start)}→{_fmt_s(hh.frequency_end)}"
        if hh.amplitude_start or hh.amplitude_end:
            s += f"、幅度{_fmt_s(hh.amplitude_start)}→{_fmt_s(hh.amplitude_end)}"
        eas = _cn(_EASING_CN, hh.easing)
        if eas and eas != "匀速":
            s += f"({eas})"
        bits.append(s)

    fc = cc.focus
    if fc and (fc.lock_target or fc.lock_strictness in ("absolute", "rack") or fc.depth_of_field):
        f = f"焦点{_cn(_STRICTNESS_CN, fc.lock_strictness)}"
        if fc.lock_target:
            f += f"在{fc.lock_target}"
        if fc.lock_strictness == "rack" and fc.rack_to:
            f += f",移向{fc.rack_to}"
        if fc.depth_of_field:
            f += f",景深{fc.depth_of_field}"
        bits.append(f)

    mv = cc.movement
    if mv and mv.type and mv.type != "static":
        m = _cn(_MOVEMENT_CN, mv.type) or mv.type
        if mv.speed_start or mv.speed_end:
            m += f"(速度{_fmt_s(mv.speed_start)}→{_fmt_s(mv.speed_end)})"
        if mv.distance:
            m += f",{mv.distance}"
        bits.append(m)

    br = cc.breathing
    if br and br.enabled:
        b = "镜头呼吸感"
        sync = _cn(_SYNC_CN, br.sync_to)
        if sync:
            b += f"({sync})"
        bits.append(b)

    return "运镜:" + "、".join(bits) if bits else ""


def _compile_prop(props: list) -> str:
    """PropPerformance[] → 道具表演自然语言(状态机/位移/指向偏移/颤动/表面/画面位置)。空 → ''。"""
    bits: list[str] = []
    for p in props or []:
        name = p.prop_ref or p.prop_type or "道具"
        seg: list[str] = []
        cs = p.contact_state
        if cs.state:
            s = _cn(_CONTACT_STATE_CN, cs.state)
            if cs.hold_reason:
                s += f"({cs.hold_reason})"
            seg.append(s)
        md = p.micro_displacement
        if md.distance_mm:
            m = f"{md.axis or ''}位移{_fmt_s(md.distance_mm)}mm"
            if md.suspended:
                m += "悬停"
            seg.append(m)
        ao = p.aim_offset
        if ao.magnitude_desc:
            seg.append(f"指向偏移{ao.magnitude_desc}")
        elif (ao.start.x, ao.start.y) != (ao.end.x, ao.end.y):
            seg.append(
                f"指向从({_fmt_s(ao.start.x)},{_fmt_s(ao.start.y)})"
                f"移到({_fmt_s(ao.end.x)},{_fmt_s(ao.end.y)})"
            )
        if p.tremor.amplitude_mm:
            seg.append(f"颤动{_fmt_s(p.tremor.amplitude_mm)}mm")
        if p.surface_response.material_highlight:
            seg.append(p.surface_response.material_highlight)
        if p.surface_response.deformation_state:
            seg.append(p.surface_response.deformation_state)
        if p.frame_presence.position_desc:
            seg.append(f"位于{p.frame_presence.position_desc}")
        if seg:
            bits.append(f"{name}:" + "、".join(seg))
    return "道具:" + ";".join(bits) if bits else ""


def _compile_lighting(lr) -> str:
    """LightingResponse → 光的响应自然语言(明暗比/遮挡阴影/高光/光型)。未填 → ''。"""
    if lr is None:
        return ""
    bits: list[str] = []
    kr = lr.key_ratio
    if kr.lit_side or kr.shadow_side:
        s = f"受光{kr.lit_side}" if kr.lit_side else ""
        if kr.shadow_side:
            s += ("、" if s else "") + f"阴影{kr.shadow_side}"
        if kr.contrast_level:
            s += f"(明暗比{_fmt_s(kr.contrast_level)})"
        bits.append(s)
    oc = lr.occlusion
    delta = _cn(_SHADOW_DELTA_CN, oc.shadow_delta)
    if delta:
        bits.append(
            f"{oc.cause}使{oc.affected_area or '面部'}{delta}"
            if oc.cause
            else f"{oc.affected_area or '面部'}{delta}"
        )
    if lr.specular_targets:
        bits.append("高光:" + "、".join(lr.specular_targets))
    pat = _cn(_PATTERN_CN, lr.pattern)
    if pat:
        bits.append(pat)
    return "光:" + ";".join(bits) if bits else ""


def _phase_parts(ph: PerformancePhase, *, include_camera: bool = True) -> list[str]:
    """一段表演的内容部分(不含 [时间窗] 头)。include_camera=False 用于静态关键帧注入
    (运镜是运动、静帧渲不出,只给面部/视线/情绪/身体/道具/光)。"""
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

    prop = _compile_prop(ph.prop_performance)
    if prop:
        parts.append(prop)

    lighting = _compile_lighting(ph.lighting_response)
    if lighting:
        parts.append(lighting)

    if include_camera:
        camera = _compile_camera(ph.camera_curve)
        if camera:
            parts.append(camera)

    return parts


def _compile_phase(ph: PerformancePhase) -> str:
    head = f"[{_fmt_s(ph.t_start_s)}–{_fmt_s(ph.t_end_s)}s]"
    if ph.label:
        head += f" {ph.label}"
    parts = _phase_parts(ph)
    return head + " → " + ";".join(parts) if parts else head


def compile_temporal_prompt(track: PerformanceTrack | None) -> str:
    """PerformanceTrack → 时序提示词(逐段时间窗自然语言)。空 → 空串(inert,拼接方无副作用)。"""
    if track is None or not track.phases:
        return ""
    phases = sorted(track.phases, key=lambda p: (p.order, p.t_start_s))
    return "\n".join(_compile_phase(ph) for ph in phases)


def phase_at_time(track: PerformanceTrack | None, t: float) -> PerformancePhase | None:
    """时刻 t 落在哪一段(半开区间 [start, end))。越界钳到首/末段。空 → None。"""
    if track is None or not track.phases:
        return None
    phases = sorted(track.phases, key=lambda p: (p.order, p.t_start_s))
    for ph in phases:
        if ph.t_start_s <= t < ph.t_end_s:
            return ph
    return phases[-1] if t >= phases[-1].t_end_s else phases[0]


def beat_slices(track: PerformanceTrack | None) -> dict[str, str]:
    """§1.1 phase→beat 时间映射:表演时间轴按 first(t=0)/peak(中点)/aftermath(末)三个
    时刻切片,注入渲染对应关键帧(首/关键/尾帧)。静帧渲不出运镜 → 只给面部/视线/情绪/身体
    (include_camera=False)。空 track → {}(inert,渲染层无副作用)。"""
    if track is None or not track.phases:
        return {}
    total = track.total_duration_s or max((p.t_end_s for p in track.phases), default=0.0)
    if total <= 0:
        return {}
    out: dict[str, str] = {}
    for role, t in (("first", 0.0), ("peak", total / 2.0), ("aftermath", total - _EPS)):
        ph = phase_at_time(track, t)
        parts = _phase_parts(ph, include_camera=False) if ph else []
        if parts:
            out[role] = "；".join(parts)
    return out


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

    # ── P2(第三批):焦点 absolute 死锁时不得同时有 rack_to(自相矛盾)──
    findings.extend(
        PerformanceLintFinding(
            "P2",
            shot_id,
            [ph.phase_id],
            f"焦点 absolute 死锁却又指定 rack_to={ph.camera_curve.focus.rack_to}(自相矛盾)",
        )
        for ph in phases
        if ph.camera_curve
        and ph.camera_curve.focus.lock_strictness == "absolute"
        and ph.camera_curve.focus.rack_to
    )

    # ── P4(第三批):handheld 频率跨 phase 边界必须连续(前 end = 后 start),否则晃动突变 ──
    for a, b in pairwise(phases):
        ca, cb = a.camera_curve, b.camera_curve
        if ca is None or cb is None or not ca.handheld.enabled or not cb.handheld.enabled:
            continue
        if abs(ca.handheld.frequency_end - cb.handheld.frequency_start) > _EPS:
            findings.append(
                PerformanceLintFinding(
                    "P4",
                    shot_id,
                    [a.phase_id, b.phase_id],
                    f"手持频率跨边界突变:{_fmt_s(ca.handheld.frequency_end)} vs "
                    f"{_fmt_s(cb.handheld.frequency_start)}",
                )
            )

    # ── P6(第三批):守恒律——面部细节密度高 且 身体大幅运动 → 警告(细节×运动超上限,v3.2 §7.2b)──
    findings.extend(
        PerformanceLintFinding(
            "P6",
            shot_id,
            [ph.phase_id],
            f"面部细节密度({_facial_density(ph.facial_performance)})与身体大幅运动"
            f"({ph.body.tension})并存,恐超「细节×运动」上限,建议二选一或降采样",
            severity="warn",
        )
        for ph in phases
        if _facial_density(ph.facial_performance) >= 4
        and ph.body.tension in ("trembling", "collapsing")
    )

    # ── P7(v0.2):道具接触状态机跨 phase 转移合法(按 prop_type 图;guard→threshold 非法)──
    for a, b in pairwise(phases):
        prev_by_type = {
            p.prop_type: p.contact_state.state for p in a.prop_performance if p.prop_type
        }
        for p in b.prop_performance:
            graph = _PROP_STATE_GRAPH.get(p.prop_type)
            prev = prev_by_type.get(p.prop_type)
            cur = p.contact_state.state
            if not graph or not prev or not cur or prev not in graph:
                continue
            if cur not in graph[prev]:
                findings.append(
                    PerformanceLintFinding(
                        "P7",
                        shot_id,
                        [a.phase_id, b.phase_id],
                        f"道具({p.prop_type})状态跳变 {prev}→{cur}(非法转移,须逐级经中间态)",
                    )
                )

    # ── P9(v0.2):光的响应——阴影变化必须说明遮挡原因(source 在 SceneStage 的校验在桥接层做)──
    findings.extend(
        PerformanceLintFinding(
            "P9",
            shot_id,
            [ph.phase_id],
            f"阴影{_cn(_SHADOW_DELTA_CN, ph.lighting_response.occlusion.shadow_delta)}"
            f"但未说明遮挡原因(occlusion.cause 空)——恐凭空改光",
        )
        for ph in phases
        if ph.lighting_response
        and ph.lighting_response.occlusion.shadow_delta
        and not ph.lighting_response.occlusion.cause
    )
    return findings


def _facial_density(fp: FacialPerformance | None) -> int:
    """面部细节密度粗量(P6 守恒律用):muscle_actions 条数 + 生理非默认字段数。"""
    if fp is None:
        return 0
    phy = fp.physiology
    return len(fp.muscle_actions) + sum(
        bool(x)
        for x in (
            phy.tear_state not in ("none", ""),
            phy.eye_vasculature,
            phy.pupil.dilation,
            phy.blink,
            phy.swallow,
            phy.lip_state,
            phy.skin_flush,
        )
    )


def expected_handheld_trend(cc: CameraCurve | None) -> str:
    """从 handheld 频率推期望晃动趋势(camera_curve_match 用):increasing/decreasing/flat。"""
    if cc is None or not cc.handheld.enabled:
        return "flat"
    d = cc.handheld.frequency_end - cc.handheld.frequency_start
    return "increasing" if d > _EPS else "decreasing" if d < -_EPS else "flat"


def camera_curve_match(
    motion_magnitudes: list[float], expected_trend: str, *, min_frames: int = 6
) -> dict:
    """INC-002 §5.3 camera_curve_match:给逐帧运动幅度序列(光流抽帧算得,确定性、零模型),
    验其趋势是否符合预期("晃动频率是否递增")。用线性回归斜率符号判 increasing/decreasing/flat。
    帧数不足 → match=None(无法判)。真实视频→motion_magnitudes 的抽取(cv2 光流)是接入时的
    薄封装,核心趋势判定在此,可用合成序列确定性测。"""
    if len(motion_magnitudes) < min_frames:
        return {"match": None, "reason": "帧数不足", "actual_trend": None}
    n = len(motion_magnitudes)
    xs = range(n)
    mx = (n - 1) / 2.0
    my = sum(motion_magnitudes) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, motion_magnitudes, strict=False))
    den = sum((x - mx) ** 2 for x in xs)
    slope = num / den if den else 0.0
    scale = (max(motion_magnitudes) - min(motion_magnitudes)) or 1.0
    norm = slope * n / scale  # 归一化:整段跨度相对于幅度量级
    actual = "increasing" if norm > 0.15 else "decreasing" if norm < -0.15 else "flat"
    return {"match": actual == expected_trend, "actual_trend": actual, "slope": slope}


# ── INC-002 第四批:PerformancePreset 拉伸 + L0–L3 密度档降采样(§5.2 / §5.4)──────

# 密度档位(按 provider 能力路由):L0 只有 action_beats(现状);L1 +eyeline+emotional;
# L2 +facial_performance+camera_curve;L3 +muscle_actions(FACS 级)。
DENSITY_TIERS = ("L0", "L1", "L2", "L3")
_BASELINE_TIER = {
    "economy": "L0",
    "minimal": "L0",
    "standard": "L1",
    "cinematic": "L2",
    "flagship": "L3",
    "anatomical": "L3",
}


def tier_for_baseline(baseline: str) -> str:
    """按 Concept.quality_baseline 选密度档(§5.4)。未知/空 → L1(standard)。"""
    return _BASELINE_TIER.get((baseline or "").strip().lower(), "L1")


def scale_preset_to_duration(
    preset: PerformancePreset, total_duration_s: float
) -> PerformanceTrack:
    """把预设的相对时间(0–1 比例)拉伸成绝对秒的 PerformanceTrack(§5.2 可复用/可拉伸)。"""
    phases: list[PerformancePhase] = []
    for ph in preset.phases:
        p = ph.model_copy(deep=True)
        p.t_start_s = round(ph.t_start_s * total_duration_s, 3)
        p.t_end_s = round(ph.t_end_s * total_duration_s, 3)
        phases.append(p)
    return PerformanceTrack(total_duration_s=total_duration_s, phases=phases)


def downsample_track(track: PerformanceTrack | None, tier: str) -> PerformanceTrack | None:
    """按密度档裁剪(§5.4:低档 provider 收到高档 schema → 编译器自动降采样,不报错)。
    - L3:全保。
    - L2:丢 muscle_actions 的解剖结构标注,只保 visible_result(仍进 prompt)。
    - L1:丢 facial_performance + camera_curve,保 eyeline + emotional + body。
    - L0:整条 performance_track 丢掉(返回 None)→ 走 action_beats 老路。
    """
    if track is None or tier == "L3":
        return track
    if tier == "L0":
        return None
    out = track.model_copy(deep=True)
    for ph in out.phases:
        if tier == "L1":
            ph.facial_performance = None
            ph.camera_curve = None
        elif tier == "L2" and ph.facial_performance:
            # 丢 muscle/action/intensity 结构标注,只留 visible_result(§5.4)
            ph.facial_performance.muscle_actions = [
                MuscleAction(visible_result=m.visible_result)
                for m in ph.facial_performance.muscle_actions
                if m.visible_result
            ]
    return out


def compile_temporal_prompt_at_tier(track: PerformanceTrack | None, tier: str) -> str:
    """先按密度档降采样再编译——低档 provider 拿到高档 schema 也不报错(§5.4)。"""
    return compile_temporal_prompt(downsample_track(track, tier))
