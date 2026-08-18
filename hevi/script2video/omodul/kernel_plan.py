"""把自由镜头/角色 payload 编成 KernelPlan(拆镜 + 机位树)。

组合 oskill.shot_decompose + oskill.camera_tree。
"""

from __future__ import annotations

from typing import Any

from hevi.script2video.oskill.camera_tree import construct_camera_tree
from hevi.script2video.oskill.shot_decompose import decompose_all_shots
from hevi.script2video.schemas import KernelCharacter, KernelPlan, KernelShot


def _parse_cam_idx(raw: Any) -> int:
    if raw is None:
        return 0
    text = str(raw).lstrip("-")
    if text.isdigit():
        return int(raw)
    return 0


def _coalesce_key(*values: Any) -> str:
    for value in values:
        if value is None or value == "":
            continue
        return str(value)
    return ""


def shots_from_payload(items: list[dict[str, Any]]) -> list[KernelShot]:
    shots: list[KernelShot] = []
    for index, raw in enumerate(items):
        visible = raw.get("visible_chars") or raw.get("character_names") or []
        shots.append(
            KernelShot(
                idx=int(raw.get("idx", index)),
                visual_desc=str(raw.get("visual_desc") or raw.get("visual_prompt") or ""),
                cam_key=_coalesce_key(
                    raw.get("cam_key"),
                    raw.get("camera_setup_ref"),
                    raw.get("camera"),
                    raw.get("cam_idx"),
                ),
                cam_idx=_parse_cam_idx(raw.get("cam_idx")),
                environment=str(raw.get("environment") or raw.get("scene_name") or ""),
                visible_chars=[str(name) for name in visible],
                audio_desc=str(raw.get("audio_desc") or ""),
                facing_hints=dict(raw.get("facing_hints") or {}),
                azimuth_deg=raw.get("azimuth_deg"),
                action_beats=[str(beat) for beat in (raw.get("action_beats") or [])],
            )
        )
    return shots


def characters_from_payload(items: list[dict[str, Any]]) -> list[KernelCharacter]:
    characters: list[KernelCharacter] = []
    for raw in items:
        identifier = str(raw.get("identifier") or raw.get("name") or "").strip()
        if not identifier:
            continue
        characters.append(
            KernelCharacter(
                name=str(raw.get("name") or identifier),
                identifier=identifier,
                description=str(raw.get("description") or raw.get("appearance") or ""),
                reference_photo=raw.get("reference_photo"),
                is_visible=bool(raw.get("is_visible", True)),
            )
        )
    return characters


def plan_kernel_artifacts(
    shots: list[dict[str, Any]] | list[KernelShot],
    characters: list[dict[str, Any]] | list[KernelCharacter] | None = None,
) -> KernelPlan:
    normalized: list[KernelShot] = []
    for item in shots:
        if isinstance(item, KernelShot):
            normalized.append(item)
        else:
            normalized.extend(shots_from_payload([item]))
    if characters is None:
        char_models: list[KernelCharacter] = []
    else:
        char_models = [
            item if isinstance(item, KernelCharacter) else characters_from_payload([item])[0]
            for item in characters
            if isinstance(item, KernelCharacter) or (item.get("identifier") or item.get("name"))
        ]
    tree = construct_camera_tree(normalized)
    visuals = decompose_all_shots(normalized)
    return KernelPlan(
        shots=normalized,
        visual_plans=visuals,
        camera_tree=tree,
        characters=char_models,
    )
