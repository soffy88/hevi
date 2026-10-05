"""S1-10:one-line → Director 语义主干 → MissionExecutor 计划(dry-run,零执行)。

复用现有五级生成器(concept → screenplay → design_list → scene_stage → shot_list),
不新增 Director 入口。dry-run 不触付费 provider、不触 GPU。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.creative.autonomous.canonical import (
    DIRECTOR_ENTRY,
    KNOWN_SPLITS,
    AssetSemanticRole,
    MediaType,
    SceneStageSet,
    SourcePolicy,
    plan_summary,
    to_asset_requirement,
    to_visual_intent,
)
from hevi.creative.autonomous.manifest import ProductionManifest, StageProjection
from hevi.director.concept import generate_concept_draft
from hevi.director.design_list import generate_design_list_draft
from hevi.director.scene_stage import generate_scene_stage_draft
from hevi.director.screenplay import generate_screenplay_draft
from hevi.director.shot_list import generate_shot_list_draft


@dataclass(frozen=True)
class DryRunResult:
    production_id: str
    request: str
    summary: dict[str, Any]
    asset_requirements: tuple[dict[str, Any], ...] = ()
    stage_plan: tuple[dict[str, Any], ...] = ()
    vocabulary_splits: tuple[dict[str, str], ...] = ()

    def write(self, out_dir: Path) -> dict[str, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        for name, payload in (("plan", self.summary),
                              ("script", self.summary.get("concept", {})),
                              ("asset_plan", {"requirements": list(self.asset_requirements)}),
                              ("stage_plan", {"stages": list(self.stage_plan)})):
            path = out_dir / f"{name}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                       sort_keys=True) + "\n", encoding="utf-8")
            written[name] = path
        return written


def _stage_plan(shots: tuple[Any, ...]) -> tuple[dict[str, Any], ...]:
    """dry-run 只给阶段骨架,真实节点由 MissionExecutor 建。这里不建 PlanNode。"""
    return (
        {"stage": "SCRIPT", "status": "PLANNED", "shots": 0},
        {"stage": "STORYBOARD", "status": "PLANNED", "shots": len(shots)},
        {"stage": "ASSET_PLAN", "status": "PLANNED",
         "requirements": len(shots)},
        {"stage": "VOICE_MUSIC_SUBTITLE", "status": "PLANNED", "shots": 0},
        {"stage": "EDIT_RENDER", "status": "PLANNED", "shots": len(shots)},
        {"stage": "QC", "status": "PLANNED", "shots": 0},
        {"stage": "FINAL", "status": "PLANNED", "shots": 0},
    )


async def dry_run(prompt: str, *, out_dir: Path | None = None,
                  production_id: str = "dry-run-local") -> DryRunResult:
    """一句话 → Director 五级草稿 → shot/asset 需求。零执行、零付费调用。"""
    concept = await generate_concept_draft(material_text=prompt)
    screenplay = await generate_screenplay_draft(concept=concept, material_text=prompt)
    design_list = await generate_design_list_draft(screenplay=screenplay)
    # 逐场 SceneStage(与 director_pipeline.py:1164 `_build_scene_stage_set` 同形:
    # 复用同一生成器,单场失败只退化该场,不拖累全片)
    stages = []
    for scene in screenplay.scenes:
        # PERF401 不适用:推导式里的 await 会变成 async generator(已踩过)
        stages.append(await generate_scene_stage_draft(scene=scene, design_list=design_list))  # noqa: PERF401
    shot_list = await generate_shot_list_draft(screenplay=screenplay, design_list=design_list)

    summary = plan_summary(concept=concept, screenplay=screenplay, design_list=design_list,
                           stage_set=_as_set(stages), shot_list=shot_list)
    summary["dry_run"] = True
    summary["paid_provider_called"] = False
    summary["gpu_required"] = False

    requirements = tuple(
        to_asset_requirement(
            item,
            semantic_role=(AssetSemanticRole.CHARACTER if item.character_names
                           else AssetSemanticRole.SCENE),
            media_type=MediaType.VIDEO,
            source_policy=SourcePolicy.PREFERRED_LICENSED,
        ).to_dict()
        for item in shot_list.shots
    )
    result = DryRunResult(
        production_id=production_id, request=prompt, summary=summary,
        asset_requirements=requirements,
        stage_plan=_stage_plan(tuple(shot_list.shots)),
        vocabulary_splits=tuple({"concept": s.concept, "canonical": s.canonical, "seam": s.seam}
                                for s in KNOWN_SPLITS),
    )
    if out_dir is not None:
        result.write(out_dir)
    return result


def _as_set(stages: list[Any]) -> SceneStageSet:
    return SceneStageSet(stages=stages)


def to_manifest(result: DryRunResult) -> ProductionManifest:
    """dry-run → production_manifest(durable projection 的第一份)。"""
    return ProductionManifest(
        production_id=result.production_id, request=result.request,
        director_plan=result.summary,
        stages=tuple(StageProjection(f"dryrun:{s['stage']}", s["stage"], s["status"])
                     for s in result.stage_plan),
        assets=result.asset_requirements,
        provenance={"director_entry": DIRECTOR_ENTRY, "dry_run": True},
        status="PLANNED",
    )


__all__ = ["DryRunResult", "dry_run", "to_asset_requirement", "to_manifest", "to_visual_intent"]