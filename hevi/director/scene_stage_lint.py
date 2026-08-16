"""SPEC-004 §4 确定性守护 —— 四条零模型成本的分镜 lint(生成后跑)。

镜头引用了同一 SceneStage 后,一批穿帮就能纯规则拦下(不花一分钱、不调 LLM):
- L1 跳轴:相邻同场镜头的机位不得跨轴换侧,除非该拍有已声明的 axis_shift。
- L2 反打差异:对话反打的相邻两镜,景别至少差 2 档(否则镜像感跳切)。
- L3 eyeline 一致:镜头对白的 speaker→target 必须与 SceneStage.sightlines 在该拍一致。
- L4 剪辑冗余:每个被拍到的 beat 至少被 2 个不同机位覆盖(否则一条废全废,无剪辑余地)。

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


def lint_scene_stage(shot_list: ShotList, scene_stage_set: SceneStageSet) -> list[LintFinding]:
    """跑四条确定性 lint,返回全部 findings(空 = 干净)。只作用于接了场事实的镜头。"""
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
    return findings
