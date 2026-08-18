"""H3 cut-budget + optional recipe findings (LintFinding, no LLM)."""

from __future__ import annotations

from hevi.director.pipeline_schemas import ShotList
from hevi.director.scene_stage_lint import LintFinding
from hevi.prompt.h3_compiler import (
    MAX_CUT_SECONDS,
    MAX_SEGMENT_SECONDS,
    MIN_CUT_SECONDS,
    pack_h3_segments,
    shot_duration_s,
)
from hevi.prompt.h3_recipes import RecipeCard, lint_h3_camera, lint_recipes


def lint_h3_cut_budget(shot_list: ShotList) -> list[LintFinding]:
    """H1: each cut 2–5s. H2: packed same-scene segment ≤15s."""
    findings: list[LintFinding] = []
    for shot in shot_list.shots:
        dur = shot_duration_s(shot)
        if MIN_CUT_SECONDS <= dur <= MAX_CUT_SECONDS:
            continue
        findings.append(
            LintFinding(
                rule="H1",
                scene_no=int(shot.scene_no or 0),
                shot_ids=[shot.shot_id],
                message=(
                    f"{shot.shot_id} 时长 {dur:.2f}s 不在 "
                    f"{MIN_CUT_SECONDS:.0f}–{MAX_CUT_SECONDS:.0f}s"
                ),
                severity="error",
            )
        )
    for group in pack_h3_segments(list(shot_list.shots)):
        total = sum(shot_duration_s(s) for s in group)
        if total <= MAX_SEGMENT_SECONDS:
            continue
        findings.append(
            LintFinding(
                rule="H2",
                scene_no=int(getattr(group[0], "scene_no", 0) or 0),
                shot_ids=[s.shot_id for s in group],
                message=f"H3 段打包 {total:.2f}s 超过 {MAX_SEGMENT_SECONDS:.0f}s",
                severity="error",
            )
        )
    return findings


def lint_h3_vocab(
    shot_list: ShotList,
    *,
    cards: dict[str, RecipeCard] | None = None,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for rule, shot_id, message in lint_h3_camera(list(shot_list.shots)):
        findings.append(
            LintFinding(rule=rule, scene_no=0, shot_ids=[shot_id], message=message)
        )
    for rule, shot_id, message in lint_recipes(list(shot_list.shots), cards):
        findings.append(
            LintFinding(
                rule=rule,
                scene_no=0,
                shot_ids=[shot_id],
                message=message,
                severity="error",
            )
        )
    return findings
