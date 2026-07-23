"""SPEC-004 §4 确定性守护 —— 六条零模型成本的分镜 lint(生成后跑)。

镜头引用了同一 SceneStage 后,一批穿帮就能纯规则拦下(不花一分钱、不调 LLM):
- L1 跳轴:相邻同场镜头的机位不得跨轴换侧,除非该拍有已声明的 axis_shift。
- L2 反打差异:对话反打的相邻两镜,景别至少差 2 档(否则镜像感跳切)。
- L3 eyeline 一致:镜头对白的 speaker→target 必须与 SceneStage.sightlines 在该拍一致。
- L4 剪辑冗余:每个被拍到的 beat 至少被 2 个不同机位覆盖(否则一条废全废,无剪辑余地)。
- L5 落位契约:④分镜 blocking 文本写的左右不能跟③.5 SceneStage.axis.side_convention 矛盾
  (2026-07-18 加,见下方 `_lint_side_convention_conflicts` docstring)。
- L6 对话戏 coverage 配比:出场人物 ≥2 且含对白的场次,shot_type 分布必须像"一场戏的
  coverage"而不是"单人特写清单"(INC-004 §1.3 加,见下方 `_lint_dialogue_coverage` docstring)。

输入是 link_shots_to_scene_stage 之后的 (ShotList, SceneStageSet)。未接场事实的镜头(无
scene_stage_ref)整体跳过——lint 只作用于走了 SPEC-004 场事实链路的镜头。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from hevi.director.pipeline_schemas import (
    CameraSetup,
    SceneStage,
    SceneStageSet,
    ShotList,
    ShotListItem,
)
from hevi.director.scene_stage import _parse_side_convention


@dataclass
class LintFinding:
    rule: str  # L1/L2/L3/L4
    scene_no: int
    shot_ids: list[str]
    message: str
    severity: str = "warn"


# 景别档位:远0 / 全1 / 中2 / 近3 / 特写4。按关键词从"细"到"粗"匹配(先特写,避免"近特写"被"近"抢)。
_SIZE_RANKS = (("特写", 4), ("近", 3), ("中", 2), ("全", 1), ("远", 0))


def _shot_size_rank(text: str) -> int | None:
    t = (text or "").strip()
    for kw, rank in _SIZE_RANKS:
        if kw in t:
            return rank
    return None


def _axis_side(text: str) -> str | None:
    """机位在主轴哪一侧,规范化到 left/right(其余/空 → None,无法判定则不拦)。"""
    t = (text or "").strip().lower()
    if "left" in t or "左" in t or t in {"a", "a侧"}:
        return "left"
    if "right" in t or "右" in t or t in {"b", "b侧"}:
        return "right"
    return None


def _setup_lookup(stage: SceneStage) -> dict[str, CameraSetup]:
    d = {s.setup_id: s for s in stage.coverage_plan.setups}
    if stage.coverage_plan.master:
        d.setdefault(stage.coverage_plan.master.setup_id, stage.coverage_plan.master)
    return d


def _lint_axis_jumps(shots: list[ShotListItem], stage: SceneStage) -> list[LintFinding]:
    """L1 跳轴:相邻镜头机位不得跨轴换侧,除非后一镜的 beat_range 里有已声明的 axis_shift。"""
    setups = _setup_lookup(stage)
    shift_beats = {sh.at_beat for sh in stage.axis.axis_shifts if sh.at_beat}
    findings: list[LintFinding] = []

    def side(shot: ShotListItem) -> str | None:
        cs = setups.get(shot.camera_setup_ref)
        return _axis_side(cs.axis_side) if cs else None

    for prev, cur in pairwise(shots):
        a, b = side(prev), side(cur)
        if a is None or b is None or a == b:
            continue
        if shift_beats & set(cur.beat_range):
            continue  # 该拍合法转轴,不算跳轴
        findings.append(
            LintFinding(
                rule="L1",
                scene_no=stage.scene_ref,
                shot_ids=[prev.shot_id, cur.shot_id],
                message=f"越轴:{prev.shot_id}({a})→{cur.shot_id}({b}) 跨主轴换侧、无 axis_shift",
            )
        )
    return findings


def _is_reverse_pair(prev: ShotListItem, cur: ShotListItem) -> bool:
    """反打:相邻两镜主要拍不同的人(视角对调)——用注意力焦点是否不同近似判定。"""
    return bool(
        prev.attention_ref and cur.attention_ref and prev.attention_ref != cur.attention_ref
    )


def _lint_reverse_size(shots: list[ShotListItem], stage: SceneStage) -> list[LintFinding]:
    """L2 反打差异:反打的相邻两镜景别至少差 2 档,否则镜像感跳切。"""
    findings: list[LintFinding] = []
    for prev, cur in pairwise(shots):
        if not _is_reverse_pair(prev, cur):
            continue
        ra, rb = _shot_size_rank(prev.shot_size), _shot_size_rank(cur.shot_size)
        if ra is None or rb is None:
            continue
        if abs(ra - rb) < 2:
            findings.append(
                LintFinding(
                    rule="L2",
                    scene_no=stage.scene_ref,
                    shot_ids=[prev.shot_id, cur.shot_id],
                    message=f"反打景别差不足 2 档({prev.shot_size}↔{cur.shot_size}),镜像感跳切",
                )
            )
    return findings


def _lint_eyeline(shots: list[ShotListItem], stage: SceneStage) -> list[LintFinding]:
    """L3 eyeline 一致:镜头对白 speaker→target 必须与 SceneStage.sightlines 在该拍一致。"""
    # (beat_id, char) → looking_at
    sl = {(s.at_beat, s.char_id): s.looking_at for s in stage.blocking.sightlines}
    findings: list[LintFinding] = []
    for shot in shots:
        beat_set = set(shot.beat_range)
        for dl in shot.dialogue_lines:
            speaker = (dl.character_name or "").strip()
            target = (dl.target_name or "").strip()
            if not speaker or not target:
                continue
            for beat in beat_set:
                look = sl.get((beat, speaker))
                if look and look != target:
                    findings.append(
                        LintFinding(
                            rule="L3",
                            scene_no=stage.scene_ref,
                            shot_ids=[shot.shot_id],
                            message=(
                                f"{shot.shot_id}:{speaker} 说给「{target}」,"
                                f"场事实视线却看「{look}」"
                            ),
                        )
                    )
                    break
    return findings


def _lint_coverage_redundancy(shots: list[ShotListItem], stage: SceneStage) -> list[LintFinding]:
    """L4 剪辑冗余:每个被拍到的 beat 至少被 2 个不同机位覆盖(装配余地)。"""
    covered: dict[str, set[str]] = {}
    for shot in shots:
        if not shot.camera_setup_ref:
            continue
        for beat in shot.beat_range:
            covered.setdefault(beat, set()).add(shot.camera_setup_ref)
    findings: list[LintFinding] = []
    for beat, setups in sorted(covered.items()):
        if len(setups) < 2:
            findings.append(
                LintFinding(
                    rule="L4",
                    scene_no=stage.scene_ref,
                    shot_ids=[s.shot_id for s in shots if beat in s.beat_range],
                    message=f"beat {beat} 只被 {len(setups)} 个机位覆盖,无剪辑余地(一条废全废)",
                )
            )
    return findings


def _lint_side_convention_conflicts(
    shots: list[ShotListItem], stage: SceneStage
) -> list[LintFinding]:
    """L5 落位契约:④分镜 blocking 文本写的左右,不能跟③.5 SceneStage.axis.side_convention
    矛盾。side_convention 是场级契约("恒"字面意思上的承诺,专为防跳轴设计),渲染层
    (`hevi.tongjian.scene_render_avatar._layout_col`)2026-07-18 起已改成 side_convention
    优先于 blocking 文本——矛盾发生时渲染层会压下矛盾按 side_convention 来(运行时保命),
    但那样矛盾本身就被默默纠正、没人知道 LLM 在这一镜写反了。这条 lint 就是把矛盾曝出来:
    检查"结果层"(blocking 具体写了什么)是否符合"计划层"(side_convention 的约定),而不是
    只查 L1-L4 那种"计划本身是否齐全/自洽"——查产出对不对,是这类 lint 的第一个实例。"""
    text = stage.axis.side_convention
    if not text:
        return []
    char_names = {b.character_name for shot in shots for b in shot.blocking if b.character_name}
    expected = _parse_side_convention(text, char_names)
    if not expected:
        return []
    findings: list[LintFinding] = []
    for shot in shots:
        for b in shot.blocking:
            want = expected.get(b.character_name)
            got = _axis_side(b.position)
            if want and got and want != got:
                findings.append(
                    LintFinding(
                        rule="L5",
                        scene_no=stage.scene_ref,
                        shot_ids=[shot.shot_id],
                        message=(
                            f"{shot.shot_id}:{b.character_name} blocking 写「{b.position}」"
                            f"(→{got}),跟 side_convention 约定的「{want}」矛盾——"
                            f"LLM 这一镜写反了,已按 side_convention 渲染"
                        ),
                    )
                )
    return findings


_RELATION_SHOT_TYPES = {"master", "two_shot"}


def _dialogue_speaker(shot: ShotListItem) -> str | None:
    return shot.dialogue_lines[0].character_name or None if shot.dialogue_lines else None


def _lint_dialogue_coverage(shots: list[ShotListItem], stage: SceneStage) -> list[LintFinding]:
    """L6 对话戏 coverage 配比(INC-004 §1.3,治"单人像跳来跳去"病1)。④分镜若只切
    clean_single 轮播,没有 master/two_shot/ots 这些让观众感知"两人同处一室"的镜头类型,
    渲染层再强也只是单人独白轮播拼接——这条 lint 在生成侧就把"没切关系镜"曝出来,不等
    渲到成片才发现观感不对。只作用于"出场人物 ≥2 且含对白"的场次(单人场/纯动作场不适用,
    没有"关系"可建立)。

    L6a 开场必须 master/two_shot(error,不这样观众看不到两人的空间关系就直接进对白)。
    L6b clean_single 占比 > 40%(warn,提示切太多单人、关系镜不够)。
    L6c 相邻两镜都是 clean_single 且说话人不同 = 单人轮播反打(warn,建议改 ots——那样才能
        同时看到"谁在说"和"另一人在旁边听着",不是各自单独录了台词拼起来)。
    L6d 连续 5 镜没有 two_shot/master(warn,空间关系太久没重建,观众会忘记两人还在一起)。
    """
    all_chars = {c for shot in shots for c in shot.character_names}
    has_dialogue = any(shot.dialogue_lines for shot in shots)
    if len(all_chars) < 2 or not has_dialogue:
        return []

    findings: list[LintFinding] = []

    if shots and shots[0].shot_type not in _RELATION_SHOT_TYPES:
        findings.append(
            LintFinding(
                rule="L6a",
                scene_no=stage.scene_ref,
                shot_ids=[shots[0].shot_id],
                message=(
                    f"{shots[0].shot_id}:开场镜 shot_type="
                    f"{shots[0].shot_type or '(未分类)'},不是 master/two_shot——"
                    "对白戏开场必须先建立两人空间关系,不能一上来就是单人/过肩"
                ),
                severity="error",
            )
        )

    single_ratio = sum(1 for s in shots if s.shot_type == "clean_single") / len(shots)
    if single_ratio > 0.4:
        findings.append(
            LintFinding(
                rule="L6b",
                scene_no=stage.scene_ref,
                shot_ids=[s.shot_id for s in shots],
                message=(
                    f"clean_single 占比 {single_ratio:.0%} > 40%,关系镜(master/two_shot/ots)不够"
                ),
            )
        )

    for prev, cur in pairwise(shots):
        if prev.shot_type != "clean_single" or cur.shot_type != "clean_single":
            continue
        sp, sc = _dialogue_speaker(prev), _dialogue_speaker(cur)
        if sp and sc and sp != sc:
            findings.append(
                LintFinding(
                    rule="L6c",
                    scene_no=stage.scene_ref,
                    shot_ids=[prev.shot_id, cur.shot_id],
                    message=(
                        f"{prev.shot_id}({sp})→{cur.shot_id}({sc}):相邻单人轮播反打,"
                        "建议改 ots(同时带出说话人+听话人,不是各自单独录台词拼起来)"
                    ),
                )
            )

    run_start = 0
    for i, shot in enumerate(shots):
        if shot.shot_type in _RELATION_SHOT_TYPES:
            run_start = i + 1
            continue
        if i - run_start + 1 == 5:
            findings.append(
                LintFinding(
                    rule="L6d",
                    scene_no=stage.scene_ref,
                    shot_ids=[s.shot_id for s in shots[run_start : i + 1]],
                    message=(
                        f"{shots[run_start].shot_id}..{shot.shot_id}:连续 5 镜无 "
                        "two_shot/master,空间关系太久没重建"
                    ),
                )
            )
            run_start = i + 1  # 从下一镜重新计数,避免同一段连续超长时报告重叠

    return findings


def lint_scene_stage(shot_list: ShotList, scene_stage_set: SceneStageSet) -> list[LintFinding]:
    """跑六条确定性 lint,返回全部 findings(空 = 干净)。只作用于接了场事实的镜头。"""
    stage_by_ref = {s.scene_ref: s for s in scene_stage_set.stages}
    findings: list[LintFinding] = []
    # 按场分组(shots 已按 scene_no 排布),逐场跑
    by_scene: dict[int, list[ShotListItem]] = {}
    for shot in shot_list.shots:
        if shot.scene_stage_ref is None:
            continue
        by_scene.setdefault(shot.scene_stage_ref, []).append(shot)
    for ref, shots in by_scene.items():
        stage = stage_by_ref.get(ref)
        if stage is None:
            continue
        findings += _lint_axis_jumps(shots, stage)
        findings += _lint_reverse_size(shots, stage)
        findings += _lint_eyeline(shots, stage)
        findings += _lint_coverage_redundancy(shots, stage)
        findings += _lint_side_convention_conflicts(shots, stage)
        findings += _lint_dialogue_coverage(shots, stage)
    return findings
