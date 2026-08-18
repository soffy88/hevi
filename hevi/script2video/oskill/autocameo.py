"""参考照片 → 锁身份角色,并入角色表。

组合: cameo_bind + portrait_triptych(可选生图)。
3O 归属(待上游): `oskill.autocameo`。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from hevi.script2video.adapter_schemas import CameoCharacter, CameoPlan, PersonInfo
from hevi.script2video.oprim.cameo_bind import (
    cameo_identifier,
    choose_role,
    default_description,
    display_name_from_photo,
)
from hevi.script2video.schemas import KernelCharacter, PortraitRegistry

ImageGenFn = Callable[..., Awaitable[Path]]


def person_from_photo(photo: Path) -> PersonInfo:
    if not photo.exists():
        raise FileNotFoundError(photo)
    name = display_name_from_photo(photo)
    return PersonInfo(
        name=name.title(),
        description=default_description(name.title(), photo),
        features=["identity-lock from reference photo"],
    )


def integrate_cameos(
    cameos: list[CameoCharacter],
    existing: list[KernelCharacter] | None = None,
) -> list[KernelCharacter]:
    """客串角色插到表头;同 identifier 则替换为带照片的版本。"""
    merged: list[KernelCharacter] = [item.to_kernel_character() for item in cameos]
    seen = {char.identifier for char in merged}
    for char in existing or []:
        if char.identifier in seen:
            continue
        merged.append(char)
    return merged


async def process_cameo_photos(
    photos: list[Path],
    *,
    story_context: str = "",
    max_characters: int = 4,
    image_gen: ImageGenFn | None = None,
    output_dir: Path | None = None,
    style: str = "cinematic",
) -> CameoPlan:
    notes: list[str] = []
    characters: list[CameoCharacter] = []
    for index, photo in enumerate(photos[: max(0, max_characters)]):
        info = person_from_photo(Path(photo))
        ident = cameo_identifier(info.name, index=index)
        role = choose_role(story_context, index=index)
        registry = None
        if image_gen is not None and output_dir is not None:
            from hevi.script2video.oskill.portrait_triptych import generate_portrait_triptych

            portrait = await generate_portrait_triptych(
                character_name=info.name,
                identifier=ident,
                description=info.description,
                output_dir=output_dir,
                style=style,
                image_gen=image_gen,
                reference_photo=photo,
            )
            registry = PortraitRegistry()
            registry.register(portrait)
        characters.append(
            CameoCharacter(
                character_id=ident,
                person_info=info,
                reference_photo=Path(photo),
                role_in_story=role,
                registry=registry,
            )
        )
        notes.append(f"{info.name} → {role} ({photo.name})")
    return CameoPlan(
        characters=characters,
        integration_notes="; ".join(notes),
        merged_characters=integrate_cameos(characters),
    )
