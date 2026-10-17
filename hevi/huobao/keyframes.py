"""Keyframe generator for assets and storyboard shots on CPU.

Adheres strictly to CPU-only execution using SD-Turbo CPU engine with
guofeng_anime style presets.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.huobao.assets import AssetRegistry, CharacterAsset, PropAsset, SceneAsset
from hevi.layer4_legacy.keyframe.oprim_impl.registry import resolve_keyframe_engine
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import get_style_preset

logger = logging.getLogger(__name__)

STYLE_NAME = "guofeng_anime"

_LEAN_ENGINE_REGISTERED = False


def _ensure_lean_engine_registered() -> None:
    """Register the memory-lean fp16 SD-Turbo engine once (idle-safe)."""
    global _LEAN_ENGINE_REGISTERED
    if _LEAN_ENGINE_REGISTERED:
        return
    from hevi.huobao.keyframe_engine_fp16 import build_lean_fp16_engine
    from hevi.layer4_legacy.keyframe.oprim_impl.registry import register_engine

    register_engine("sdturbo_cpu_fp16", engine=build_lean_fp16_engine())
    _LEAN_ENGINE_REGISTERED = True


def _build_character_prompt(char: CharacterAsset, style_tokens: str) -> str:
    parts = [
        "Chinese guofeng anime illustration",
        "donghua style",
        "character portrait bust shot",
        "detailed facial features",
        "clean elegant traditional attire",
        char.appearance or "graceful and poised expression",
        char.styling or "delicate hair and traditional robes",
        style_tokens,
    ]
    return ", ".join(p for p in parts if p)


def _build_scene_prompt(scene: SceneAsset, style_tokens: str) -> str:
    parts = [
        "Chinese guofeng anime illustration",
        "donghua architectural landscape",
        "empty scene without any humans or people",
        "pure background scenery",
        scene.location,
        scene.prompt or "traditional timber architecture and courtyard",
        scene.lighting or "warm soft lantern light, atmospheric shadows",
        style_tokens,
    ]
    return ", ".join(p for p in parts if p)


def _build_prop_prompt(prop: PropAsset, style_tokens: str) -> str:
    parts = [
        "Chinese guofeng anime illustration",
        "close-up single item still life",
        "detailed ancient Chinese artifact",
        prop.description or f"traditional handcrafted {prop.name}",
        "centered composition, clean minimal background",
        style_tokens,
    ]
    return ", ".join(p for p in parts if p)


def generate_asset_keyframes(
    registry: AssetRegistry,
    output_dir: Path | str,
    *,
    engine_name: str = "sdturbo_cpu",
    steps: int = 2,
    width: int = 512,
    height: int = 512,
) -> dict[str, Path]:
    """Generate reference keyframe for every asset in the registry using CPU engine.

    Returns mapping of asset_id -> generated image path.
    """
    out = Path(output_dir)
    assets_dir = out / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    preset = get_style_preset(STYLE_NAME)
    _ensure_lean_engine_registered()
    engine = resolve_keyframe_engine(engine_name)
    generated: dict[str, Path] = {}

    # 1. Characters
    for char in registry.characters.values():
        img_path = assets_dir / f"char_{char.id}_{char.normalized_name}.png"
        prompt_en = _build_character_prompt(char, preset.style_tokens)
        if not img_path.is_file() or img_path.stat().st_size == 0:
            logger.info("Generating keyframe for character: %s (%s)", char.name, char.id)
            engine.generate(
                prompt_en=prompt_en,
                negative=preset.negative_prompt,
                width=width,
                height=height,
                steps=steps,
                seed=char.seed,
                output_path=img_path,
            )
        char.ref_image_path = str(img_path)
        generated[char.id] = img_path

    # 2. Scenes
    for scene in registry.scenes.values():
        img_path = assets_dir / f"scene_{scene.id}_{scene.normalized_location}.png"
        prompt_en = _build_scene_prompt(scene, preset.style_tokens)
        if not img_path.is_file() or img_path.stat().st_size == 0:
            logger.info("Generating keyframe for scene: %s (%s)", scene.location, scene.id)
            engine.generate(
                prompt_en=prompt_en,
                negative=preset.negative_prompt,
                width=width,
                height=height,
                steps=steps,
                seed=scene.seed,
                output_path=img_path,
            )
        scene.ref_image_path = str(img_path)
        generated[scene.id] = img_path

    # 3. Props
    for prop in registry.props.values():
        img_path = assets_dir / f"prop_{prop.id}_{prop.normalized_name}.png"
        prompt_en = _build_prop_prompt(prop, preset.style_tokens)
        if not img_path.is_file() or img_path.stat().st_size == 0:
            logger.info("Generating keyframe for prop: %s (%s)", prop.name, prop.id)
            engine.generate(
                prompt_en=prompt_en,
                negative=preset.negative_prompt,
                width=width,
                height=height,
                steps=steps,
                seed=prop.seed,
                output_path=img_path,
            )
        prop.ref_image_path = str(img_path)
        generated[prop.id] = img_path

    # Build asset contact sheet
    build_asset_contact_sheet(registry, out / "asset_contact_sheet.jpg")
    return generated


def build_asset_contact_sheet(
    registry: AssetRegistry,
    out_path: Path | str,
    *,
    tile_size: int = 256,
) -> Path:
    """Compose all asset reference keyframes into a single labeled contact sheet."""
    items: list[tuple[str, Path]] = []
    for c in registry.characters.values():
        if c.ref_image_path and Path(c.ref_image_path).is_file():
            items.append((f"角色: {c.name}", Path(c.ref_image_path)))
    for s in registry.scenes.values():
        if s.ref_image_path and Path(s.ref_image_path).is_file():
            items.append((f"场景: {s.location}", Path(s.ref_image_path)))
    for p in registry.props.values():
        if p.ref_image_path and Path(p.ref_image_path).is_file():
            items.append((f"道具: {p.name}", Path(p.ref_image_path)))

    if not items:
        # Create empty placeholder if no items
        empty = Image.new("RGB", (tile_size * 2, tile_size), color=(30, 30, 30))
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        empty.save(out_p, quality=90)
        return out_p

    cols = min(4, len(items))
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_size, rows * tile_size), color=(20, 20, 20))
    draw = ImageDraw.Draw(sheet)

    for idx, (label, img_file) in enumerate(items):
        r = idx // cols
        c = idx % cols
        x0 = c * tile_size
        y0 = r * tile_size
        try:
            with Image.open(img_file) as im:
                im_resized = im.convert("RGB").resize((tile_size, tile_size - 30))
                sheet.paste(im_resized, (x0, y0))
        except Exception as e:
            logger.warning("Failed to paste %s: %s", img_file, e)

        # Draw label banner at bottom of tile
        draw.rectangle([(x0, y0 + tile_size - 30), (x0 + tile_size, y0 + tile_size)], fill=(0, 0, 0))
        draw.text((x0 + 8, y0 + tile_size - 24), label, fill=(240, 240, 240))

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_p, quality=92)
    return out_p
