"""一镜出站契约:clip + 定妆 + prompt + 身份,可被解说/历史/导演导入。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ShotBrick:
    brick_id: str
    shot_id: str
    source_line: str
    prompt: str = ""
    camera: str = ""
    duration_s: float = 0.0
    subject_ids: list[str] = field(default_factory=list)
    reference_paths: list[str] = field(default_factory=list)
    clip_path: str | None = None
    audio_desc: str = ""
    scene_no: int | None = None
    character_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return dest


def brick_from_payload(raw: dict[str, Any], *, source_line: str = "director") -> ShotBrick:
    shot_id = str(raw.get("shot_id") or raw.get("id") or "").strip() or str(uuid.uuid4())[:8]
    subjects = raw.get("subject_ids") or raw.get("character_ids") or []
    refs = raw.get("reference_paths") or raw.get("refs") or []
    names = raw.get("character_names") or raw.get("characters") or []
    scene = raw.get("scene_no")
    return ShotBrick(
        brick_id=str(raw.get("brick_id") or uuid.uuid4()),
        shot_id=shot_id,
        source_line=str(raw.get("source_line") or source_line),
        prompt=str(raw.get("prompt") or raw.get("visual_prompt") or raw.get("visual_desc") or ""),
        camera=str(raw.get("camera") or raw.get("camera_setup_ref") or ""),
        duration_s=float(raw.get("duration_s") or 0.0),
        subject_ids=[str(item) for item in subjects],
        reference_paths=[str(item) for item in refs],
        clip_path=raw.get("clip_path") or raw.get("video_path"),
        audio_desc=str(raw.get("audio_desc") or raw.get("audio") or ""),
        scene_no=int(scene) if scene is not None and str(scene).lstrip("-").isdigit() else None,
        character_names=[str(item) for item in names],
    )


def brick_to_explainer_cue(brick: ShotBrick) -> dict[str, Any]:
    text = brick.audio_desc or brick.prompt or brick.shot_id
    visual = "stock" if brick.clip_path else "voiceover"
    return {
        "text": text,
        "visual_type": visual,
        "duration_hint_s": brick.duration_s,
        "brick_id": brick.brick_id,
        "clip_path": brick.clip_path,
        "reference_paths": list(brick.reference_paths),
        "subject_ids": list(brick.subject_ids),
    }


def brick_to_tongjian_shot(brick: ShotBrick) -> dict[str, Any]:
    return {
        "shot_id": brick.shot_id,
        "scene_id": f"s{brick.scene_no}" if brick.scene_no is not None else "",
        "visual_desc": brick.prompt,
        "camera": brick.camera,
        "duration_s": brick.duration_s,
        "characters": list(brick.character_names),
        "clip_path": brick.clip_path,
        "subject_ids": list(brick.subject_ids),
        "brick_id": brick.brick_id,
    }


def brick_to_director_shot(brick: ShotBrick) -> dict[str, Any]:
    return {
        "shot_id": brick.shot_id,
        "scene_no": brick.scene_no or 1,
        "camera": brick.camera,
        "visual_prompt": brick.prompt,
        "duration_s": brick.duration_s or 5.0,
        "character_names": list(brick.character_names),
        "character_subject_ids": list(brick.subject_ids),
        "brick_id": brick.brick_id,
        "clip_path": brick.clip_path,
    }


def import_brick(brick: ShotBrick, target_line: str) -> dict[str, Any]:
    if target_line in {"explainer", "kinetic_promo"}:
        return {"target": "explainer", "cue": brick_to_explainer_cue(brick)}
    if target_line in {"tongjian", "history_scene"}:
        return {"target": "tongjian", "shot": brick_to_tongjian_shot(brick)}
    return {"target": "director", "shot": brick_to_director_shot(brick)}
