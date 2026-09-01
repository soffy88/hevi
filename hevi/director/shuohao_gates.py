"""烁皓 storyboard 质量门 —— 节拍认领 / 台词装切 / H3 提示词对账。

对标 eternityspring/shuohao-skills novel-storyboard 的 coverage、dialogue-fit、
h3-structure、h3-dialogue。全部确定性,不调模型。

未接 SceneStage 的旧 work 对 B1 整体跳过(inert)。P1/P2 编译当前 ShotList,
所以即使上游没存 h3Prompt,也能拦「多句对白塞进一镜」和切点时刻漂移。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from hevi.director.pipeline_schemas import (
    SceneStageSet,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
)
from hevi.director.scene_stage_lint import LintFinding
from hevi.prompt.h3_compiler import (
    compile_h3_segment,
    pack_h3_segments,
    shot_duration_s,
    validate_h3_alignment,
)

H3_DIALOGUE_OPEN = "<d>[Chinese] "
H3_DIALOGUE_CLOSE = "</d>"

# 与通鉴 / 烁皓 novel-script 同一语速。
CHARS_PER_SECOND = 4.5


def line_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def dialogue_seconds(lines: Iterable[ShotListDialogueLine]) -> float:
    return sum(line_chars(line.text) for line in lines) / CHARS_PER_SECOND


def _cast_map(shots: list[ShotListItem]) -> dict[str, int]:
    names: list[str] = []
    for shot in shots:
        for name in (*shot.character_names, *(d.character_name for d in shot.dialogue_lines)):
            if name and name not in names:
                names.append(name)
    return {name: index for index, name in enumerate(names, start=1)}


def lint_beat_coverage(
    shot_list: ShotList,
    scene_stage: SceneStageSet | None,
) -> list[LintFinding]:
    """B1: 每场节拍被恰好一次、按镜头顺序、连续认领。"""
    if scene_stage is None:
        return []
    stages = {stage.scene_ref: stage for stage in scene_stage.stages}
    by_scene: dict[int, list[ShotListItem]] = {}
    for shot in shot_list.shots:
        by_scene.setdefault(int(shot.scene_no), []).append(shot)

    findings: list[LintFinding] = []
    for scene_no, shots in by_scene.items():
        stage = stages.get(scene_no)
        if stage is None or not stage.beats:
            continue
        if not any(shot.beat_range for shot in shots):
            continue
        expected = [beat.beat_id for beat in sorted(stage.beats, key=lambda item: item.order) if beat.beat_id]
        claimed: list[str] = []
        shot_ids = [shot.shot_id for shot in shots]
        for shot in shots:
            claimed.extend(str(item) for item in (shot.beat_range or []))
        if claimed == expected:
            continue
        seen: set[str] = set()
        dupes: list[str] = []
        for beat in claimed:
            if beat in seen:
                dupes.append(beat)
            seen.add(beat)
        missing = [beat for beat in expected if beat not in seen]
        extra = [beat for beat in claimed if beat not in set(expected)]
        if claimed != expected and not dupes and not missing and not extra:
            message = f"第 {scene_no} 场节拍认领顺序乱了: {claimed} ≠ {expected}"
        else:
            parts = []
            if missing:
                parts.append(f"没人认领 {missing}")
            if dupes:
                parts.append(f"重复认领 {dupes}")
            if extra:
                parts.append(f"场外节拍 {extra}")
            message = f"第 {scene_no} 场节拍未恰好认领: " + "；".join(parts)
        findings.append(
            LintFinding(
                rule="B1",
                scene_no=scene_no,
                shot_ids=shot_ids,
                message=message,
                severity="error",
            )
        )
    return findings


def lint_dialogue_fit(shot_list: ShotList) -> list[LintFinding]:
    """D1: 认领台词按 4.5 字/秒装得进 duration_s。"""
    findings: list[LintFinding] = []
    for shot in shot_list.shots:
        if not shot.dialogue_lines:
            continue
        need = dialogue_seconds(shot.dialogue_lines)
        have = shot_duration_s(shot)
        if need <= have + 1e-9:
            continue
        findings.append(
            LintFinding(
                rule="D1",
                scene_no=int(shot.scene_no or 0),
                shot_ids=[shot.shot_id],
                message=(
                    f"{shot.shot_id} 台词 {need:.1f}s 装不进 {have:.1f}s"
                    f"（{CHARS_PER_SECOND:g} 字/秒）"
                ),
                severity="error",
            )
        )
    return findings


def _d_block_pattern(text: str) -> re.Pattern[str]:
    return re.compile(
        re.escape(H3_DIALOGUE_OPEN) + re.escape(text) + re.escape(H3_DIALOGUE_CLOSE)
    )


def lint_h3_prompt_contract(shot_list: ShotList) -> list[LintFinding]:
    """P1 切点时刻逐字对账;P2 每句台词进 <d> 块(多句一镜必红)。"""
    findings: list[LintFinding] = []
    shots = list(shot_list.shots)
    if not shots:
        return findings
    cast = _cast_map(shots)
    for group in pack_h3_segments(shots):
        durations = [shot_duration_s(shot) for shot in group]
        render = compile_h3_segment(group, cast=cast)
        text = render.integrated_multimodal_description
        ids = [shot.shot_id for shot in group]
        scene_no = int(getattr(group[0], "scene_no", 0) or 0)
        findings.extend(
            LintFinding(
                rule="P1",
                scene_no=scene_no,
                shot_ids=ids,
                message=error,
                severity="error",
            )
            for error in validate_h3_alignment(text, durations)
        )
        for shot in group:
            lines = list(shot.dialogue_lines or [])
            if not lines:
                continue
            for index, line in enumerate(lines):
                spoken = (line.text or "").strip()
                if not spoken:
                    continue
                if _d_block_pattern(spoken).search(text):
                    continue
                why = (
                    f"{shot.shot_id} 第 {index + 1} 句对白未进 <d> 块"
                    if index == 0
                    else f"{shot.shot_id} 一镜多句,第 {index + 1} 句进不了 H3 <d> 块,应拆镜"
                )
                findings.append(
                    LintFinding(
                        rule="P2",
                        scene_no=int(shot.scene_no or 0),
                        shot_ids=[shot.shot_id],
                        message=f"{why}：「{spoken[:12]}」",
                        severity="error",
                    )
                )
    return findings


def lint_shuohao_storyboard(
    shot_list: ShotList,
    scene_stage: SceneStageSet | None = None,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    findings.extend(lint_beat_coverage(shot_list, scene_stage))
    findings.extend(lint_dialogue_fit(shot_list))
    findings.extend(lint_h3_prompt_contract(shot_list))
    return findings
