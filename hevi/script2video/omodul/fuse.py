"""把 Idea / Novel / Script / Cameo + 五核收成一份可下发的制作计划。

3O 归属:hevi 护城河(ShotList 投影 / 任务 options)。规划本身只调 oskill/omodul。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.director.kernel_bridge import plan_kernel_from_shot_list
from hevi.director.pipeline_schemas import ShotList, ShotListItem
from hevi.script2video.adapter_schemas import (
    CameoPlan,
    IdeaPlan,
    NovelPlan,
    SourceKind,
)
from hevi.script2video.omodul.idea_plan import plan_idea2video
from hevi.script2video.omodul.kernel_plan import plan_kernel_artifacts
from hevi.script2video.omodul.novel_plan import plan_novel2video
from hevi.script2video.oprim.source_route import classify_source
from hevi.script2video.oskill.autocameo import integrate_cameos, person_from_photo
from hevi.script2video.oskill.shot_decompose import last_frame_required
from hevi.script2video.schemas import KernelCharacter, KernelPlan


@dataclass
class FusedProduction:
    source: SourceKind
    shot_list: ShotList
    characters: list[KernelCharacter] = field(default_factory=list)
    kernel: KernelPlan | None = None
    idea: IdeaPlan | None = None
    novel: NovelPlan | None = None
    cameo: CameoPlan | None = None
    notes: list[str] = field(default_factory=list)

    def locked_shot_payload(self) -> dict[str, Any]:
        return {"shots": [shot.model_dump() for shot in self.shot_list.shots]}

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "shot_count": len(self.shot_list.shots),
            "characters": [char.identifier for char in self.characters],
            "notes": list(self.notes),
            "kernel": self.kernel.to_dict() if self.kernel else None,
            "idea": self.idea.to_dict() if self.idea else None,
            "novel": self.novel.to_dict() if self.novel else None,
            "cameo": self.cameo.to_dict() if self.cameo else None,
            "locked_shot_list": self.locked_shot_payload(),
        }


def kernel_plan_to_shot_list(plan: KernelPlan, *, scene_no: int = 1) -> ShotList:
    """五核视觉计划 → Hevi ShotList(给 locked_shot_list / 导演台)。"""
    by_idx = {shot.idx: shot for shot in plan.shots}
    items: list[ShotListItem] = []
    for visual in plan.visual_plans:
        src = by_idx.get(visual.idx)
        beats = [part.strip() for part in visual.motion_desc.split("→") if part.strip()]
        items.append(
            ShotListItem(
                shot_id=f"K{scene_no:02d}_{visual.idx:03d}",
                scene_no=scene_no,
                visual_prompt=visual.ff_desc or visual.visual_desc,
                action_beats=beats,
                character_names=list(src.visible_chars) if src else [],
                scene_name=src.environment if src else "",
                camera_setup_ref=f"cam_{visual.cam_idx}",
                duration_s=4.0 if visual.variation_type == "small" else 5.0,
            )
        )
    return ShotList(shots=items)


def enrich_shot_list_with_kernel(shot_list: ShotList, plan: KernelPlan) -> ShotList:
    """已有分镜只补空位:机位键 / 动作弧。不改已写好的 visual_prompt。"""
    by_idx = {visual.idx: visual for visual in plan.visual_plans}
    enriched: list[ShotListItem] = []
    for index, shot in enumerate(shot_list.shots):
        visual = by_idx.get(index)
        if visual is None:
            enriched.append(shot)
            continue
        updates: dict[str, Any] = {}
        if not shot.camera_setup_ref:
            updates["camera_setup_ref"] = f"cam_{visual.cam_idx}"
        if not shot.action_beats and visual.motion_desc:
            beats = [part.strip() for part in visual.motion_desc.split("→") if part.strip()]
            if beats:
                updates["action_beats"] = beats
        enriched.append(shot.model_copy(update=updates) if updates else shot)
    return ShotList(shots=enriched)


def shot_list_from_kernels(kernels: list[KernelPlan]) -> ShotList:
    shots: list[ShotListItem] = []
    for scene_no, kernel in enumerate(kernels, start=1):
        shots.extend(kernel_plan_to_shot_list(kernel, scene_no=scene_no).shots)
    return ShotList(shots=shots)


def cameo_plan_from_photos(
    photos: list[Path],
    *,
    story_context: str = "",
    max_characters: int = 4,
) -> CameoPlan:
    """同步、不调生图:只锁身份并进角色表。"""
    from hevi.script2video.adapter_schemas import CameoCharacter
    from hevi.script2video.oprim.cameo_bind import cameo_identifier, choose_role

    characters: list[CameoCharacter] = []
    notes: list[str] = []
    for index, photo in enumerate(photos[: max(0, max_characters)]):
        path = Path(photo)
        info = person_from_photo(path)
        ident = cameo_identifier(info.name, index=index)
        role = choose_role(story_context, index=index)
        characters.append(
            CameoCharacter(
                character_id=ident,
                person_info=info,
                reference_photo=path,
                role_in_story=role,
            )
        )
        notes.append(f"{info.name} → {role}")
    return CameoPlan(
        characters=characters,
        integration_notes="; ".join(notes),
        merged_characters=integrate_cameos(characters),
    )


def fuse_production(
    text: str,
    *,
    requirement: str = "",
    style: str = "",
    photos: list[Path] | None = None,
    explicit: SourceKind | None = None,
    existing_shot_list: ShotList | None = None,
    existing_characters: list[KernelCharacter] | None = None,
) -> FusedProduction:
    """一条入口:分流 + 客串并入 + 五核规划 + ShotList。失败不该发生;空文本仍给空片单。"""
    notes: list[str] = []
    cameo = None
    if photos:
        cameo = cameo_plan_from_photos(
            photos, story_context="\n".join(part for part in (text, requirement) if part)
        )
        notes.append(f"cameo:{len(cameo.characters)}")

    if existing_shot_list is not None:
        kernel = plan_kernel_from_shot_list(existing_shot_list, characters=None)
        shot_list = enrich_shot_list_with_kernel(existing_shot_list, kernel)
        characters = list(existing_characters or [])
        if cameo is not None:
            characters = integrate_cameos(cameo.characters, characters)
        return FusedProduction(
            source="script",
            shot_list=shot_list,
            characters=characters,
            kernel=kernel,
            cameo=cameo,
            notes=[*notes, "enriched existing shot_list"],
        )

    source = classify_source(text, has_photos=bool(photos), explicit=explicit)
    if source == "cameo" and (text or "").strip():
        source = classify_source(text, has_photos=False, explicit=explicit)
        notes.append("cameo overlaid on narrative")

    if source == "novel":
        novel = plan_novel2video(text)
        characters = [
            KernelCharacter(
                name=item.name,
                identifier=item.identifier,
                description=item.static_features,
            )
            for item in novel.book
        ]
        if cameo is not None:
            characters = integrate_cameos(cameo.characters, characters)
        shot_list = shot_list_from_kernels(novel.scene_kernels)
        novel_kernel = novel.scene_kernels[0] if novel.scene_kernels else None
        return FusedProduction(
            source="novel",
            shot_list=shot_list,
            characters=characters,
            kernel=novel_kernel,
            novel=novel,
            cameo=cameo,
            notes=notes,
        )

    if source == "script":
        script_kernel = plan_kernel_artifacts(
            [
                {
                    "visual_desc": text,
                    "cam_key": "master",
                    "visible_chars": [char.name for char in (existing_characters or [])],
                }
            ],
            [
                {
                    "name": char.name,
                    "identifier": char.identifier,
                    "description": char.description,
                    "reference_photo": char.reference_photo,
                }
                for char in (existing_characters or [])
            ],
        )
        characters = list(existing_characters or [])
        if cameo is not None:
            characters = integrate_cameos(cameo.characters, characters)
        return FusedProduction(
            source="script",
            shot_list=kernel_plan_to_shot_list(script_kernel),
            characters=characters,
            kernel=script_kernel,
            cameo=cameo,
            notes=notes,
        )

    idea = plan_idea2video(text or "untitled", requirement, style)
    characters = list(idea.characters)
    if cameo is not None:
        characters = integrate_cameos(cameo.characters, characters)
        idea.characters = characters
    shot_list = shot_list_from_kernels(idea.scene_kernels)
    idea_kernel = idea.scene_kernels[0] if idea.scene_kernels else None
    return FusedProduction(
        source="idea",
        shot_list=shot_list,
        characters=characters,
        kernel=idea_kernel,
        idea=idea,
        cameo=cameo,
        notes=notes,
    )


def last_frame_shot_indices(plan: KernelPlan | None) -> list[int]:
    if plan is None:
        return []
    return [
        visual.idx for visual in plan.visual_plans if last_frame_required(visual.variation_type)
    ]
