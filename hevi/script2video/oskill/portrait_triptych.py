"""角色正/侧/背三联画。

组合: `build_portrait_prompt` + 条件生图(注入) + 侧/背面失败拷贝正面。
3O 归属(待上游): `oskill.portrait_triptych`。
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from hevi.script2video.oprim.portrait_prompt import build_portrait_prompt
from hevi.script2video.schemas import (
    CharacterPortrait,
    KernelCharacter,
    PortraitRegistry,
    PortraitView,
    PortraitViewName,
)

logger = logging.getLogger(__name__)

ImageGenFn = Callable[..., Awaitable[Path]]


async def generate_portrait_view(
    view: PortraitViewName,
    *,
    identifier: str,
    features: str,
    style: str,
    output_path: Path,
    image_gen: ImageGenFn,
    reference_image_paths: list[Path] | None = None,
) -> PortraitView:
    prompt = build_portrait_prompt(
        view, identifier=identifier, features=features, style=style
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    await image_gen(
        prompt=prompt,
        output_path=output_path,
        reference_image_paths=[str(path) for path in (reference_image_paths or [])],
    )
    return PortraitView(
        view=view,
        path=output_path,
        description=f"A {view} view portrait of {identifier}.",
        generation_prompt=prompt,
    )


async def generate_portrait_triptych(
    *,
    character_name: str,
    identifier: str,
    description: str,
    output_dir: Path,
    style: str = "cinematic",
    image_gen: ImageGenFn,
    reference_photo: str | Path | None = None,
) -> CharacterPortrait:
    """正面优先(可注入 Cameo 真照片),侧/背以正面为参考;失败则拷贝正面。"""
    char_dir = Path(output_dir) / identifier
    char_dir.mkdir(parents=True, exist_ok=True)
    front_path = char_dir / "front.png"
    if reference_photo:
        src = Path(reference_photo)
        if src.exists():
            shutil.copy(src, front_path)
            front = PortraitView(
                view="front",
                path=front_path,
                description=f"A front view portrait of {identifier}.",
                generation_prompt="cameo-injected reference photo",
            )
        else:
            front = await generate_portrait_view(
                "front",
                identifier=identifier,
                features=description,
                style=style,
                output_path=front_path,
                image_gen=image_gen,
            )
    else:
        front = await generate_portrait_view(
            "front",
            identifier=identifier,
            features=description,
            style=style,
            output_path=front_path,
            image_gen=image_gen,
        )

    side = await _derived_view(
        "side",
        identifier=identifier,
        features=description,
        style=style,
        output_path=char_dir / "side.png",
        image_gen=image_gen,
        front_path=front.path,
    )
    back = await _derived_view(
        "back",
        identifier=identifier,
        features=description,
        style=style,
        output_path=char_dir / "back.png",
        image_gen=image_gen,
        front_path=front.path,
    )
    portrait = CharacterPortrait(
        name=character_name,
        identifier=identifier,
        physical_description=description,
        front=front,
        side=side,
        back=back,
        style=style,
    )
    logger.info(
        "portrait triptych done: %s (%s) → %d views",
        character_name,
        identifier,
        len(portrait.all_views),
    )
    return portrait


async def generate_all_portraits(
    characters: list[KernelCharacter] | list[dict[str, Any]],
    *,
    output_dir: Path,
    style: str = "cinematic",
    image_gen: ImageGenFn,
    existing: PortraitRegistry | None = None,
) -> PortraitRegistry:
    registry = existing or PortraitRegistry()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pending: list[KernelCharacter] = []
    for raw in characters:
        char = raw if isinstance(raw, KernelCharacter) else _character_from_dict(raw)
        if not char.is_visible:
            continue
        if char.identifier in registry.portraits:
            continue
        pending.append(char)
    if not pending:
        return registry
    for char in pending:
        try:
            portrait = await generate_portrait_triptych(
                character_name=char.name,
                identifier=char.identifier,
                description=char.description,
                output_dir=output_dir,
                style=style,
                image_gen=image_gen,
                reference_photo=char.reference_photo,
            )
            registry.register(portrait)
        except Exception:
            logger.exception("portrait generation failed: %s", char.identifier)
    _write_registry(registry, output_dir / "character_portraits_registry.json")
    return registry


async def _derived_view(
    view: PortraitViewName,
    *,
    identifier: str,
    features: str,
    style: str,
    output_path: Path,
    image_gen: ImageGenFn,
    front_path: Path,
) -> PortraitView:
    try:
        return await generate_portrait_view(
            view,
            identifier=identifier,
            features=features,
            style=style,
            output_path=output_path,
            image_gen=image_gen,
            reference_image_paths=[front_path],
        )
    except Exception as exc:
        logger.warning(
            "derived %s portrait failed for %s (%s); reusing front",
            view,
            identifier,
            exc,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(front_path, output_path)
        return PortraitView(
            view=view,
            path=output_path,
            description=f"A {view} view portrait of {identifier}.",
            generation_prompt=f"fallback-copy-front after {exc}",
        )


def _character_from_dict(raw: dict[str, Any]) -> KernelCharacter:
    identifier = str(raw.get("identifier") or raw.get("name") or "").strip()
    name = str(raw.get("name") or identifier)
    return KernelCharacter(
        name=name,
        identifier=identifier or name,
        description=str(raw.get("description") or raw.get("appearance") or ""),
        reference_photo=raw.get("reference_photo"),
        is_visible=bool(raw.get("is_visible", True)),
    )


def _write_registry(registry: PortraitRegistry, path: Path) -> None:
    import json

    path.write_text(json.dumps(registry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
