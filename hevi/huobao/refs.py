"""Storyboard prompt @reference resolution and asset binding.

Supports @角色/@场景/@道具 syntax in storyboard prompts.
Enforces:
- Unknown references raise UnknownAssetReferenceError.
- Auto-binding of asset reference images and seeds to guarantee cross-shot continuity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from hevi.huobao.assets import (
    AssetRegistry,
    CharacterAsset,
    PropAsset,
    SceneAsset,
    normalize_name,
)
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import get_style_preset

_REF_REGEX = re.compile(r"@([^\s，。！？,!?@:：]+)")


class UnknownAssetReferenceError(ValueError):
    """Raised when a prompt references an asset not registered in the registry."""


@dataclass
class ResolvedPrompt:
    original_prompt: str
    expanded_prompt_en: str
    negative_prompt: str
    effective_seed: int
    bound_characters: list[CharacterAsset] = field(default_factory=list)
    bound_scenes: list[SceneAsset] = field(default_factory=list)
    bound_props: list[PropAsset] = field(default_factory=list)
    ref_images: list[Path] = field(default_factory=list)

    @property
    def primary_character(self) -> CharacterAsset | None:
        return self.bound_characters[0] if self.bound_characters else None

    @property
    def primary_scene(self) -> SceneAsset | None:
        return self.bound_scenes[0] if self.bound_scenes else None


def parse_references(text: str) -> list[str]:
    """Extract unique asset reference names mentioned with @ prefix."""
    if not text:
        return []
    matches = _REF_REGEX.findall(text)
    seen = set()
    ordered = []
    for m in matches:
        clean = normalize_name(m)
        if clean and clean not in seen:
            seen.add(clean)
            ordered.append(clean)
    return ordered


def resolve_references(
    prompt: str,
    registry: AssetRegistry,
    *,
    base_seed: int = 42,
    shot_index: int = 0,
    style_name: str = "guofeng_anime",
) -> ResolvedPrompt:
    """Resolve all @references in the prompt against the asset registry.

    Raises:
        UnknownAssetReferenceError if any referenced asset is not registered.
    """
    ref_names = parse_references(prompt)
    bound_chars: list[CharacterAsset] = []
    bound_scenes: list[SceneAsset] = []
    bound_props: list[PropAsset] = []

    for name in ref_names:
        char = registry.find_character(name)
        if char is not None:
            if char not in bound_chars:
                bound_chars.append(char)
            continue

        prop = registry.find_prop(name)
        if prop is not None:
            if prop not in bound_props:
                bound_props.append(prop)
            continue

        # Try scene lookup
        scene = None
        for s in registry.scenes.values():
            if name in s.normalized_location or s.normalized_location in name:
                scene = s
                break
        if scene is not None:
            if scene not in bound_scenes:
                bound_scenes.append(scene)
            continue

        # Unknown asset reference
        raise UnknownAssetReferenceError(
            f"分镜提示词引用了未知资产 '@{name}'，未在资产库（角色/场景/道具）中登记"
        )

    # Collect reference images
    ref_images: list[Path] = []
    for asset in (*bound_chars, *bound_scenes, *bound_props):
        if asset.ref_image_path:
            p = Path(asset.ref_image_path)
            if p.is_file():
                ref_images.append(p)

    # Determine effective seed:
    # If primary character is present, anchor on character's fixed seed
    # with a tiny deterministic shot variance to ensure consistent face/attire!
    if bound_chars:
        # Cross-shot character consistency: seed = char.seed + (shot_index % 3)
        effective_seed = bound_chars[0].seed + (shot_index % 3)
    elif bound_scenes:
        effective_seed = bound_scenes[0].seed + shot_index
    else:
        effective_seed = base_seed + shot_index * 17

    # Build expanded prompt
    preset = get_style_preset(style_name)
    parts = [
        "Chinese guofeng anime illustration, donghua style",
        "cinematic framing",
    ]

    # Add scene context
    if bound_scenes:
        parts.append(
            f"{bound_scenes[0].location}, {bound_scenes[0].prompt or 'ancient Chinese scenery'}"
        )

    # Add action / narrative text from prompt
    # Strip @ references to create natural action description
    clean_action = _REF_REGEX.sub(r"\1", prompt).strip()
    if clean_action:
        parts.append(f"narrative action: {clean_action}")

    # Add character identity tokens to lock character appearance
    for c in bound_chars:
        parts.append(f"{c.name} ({c.appearance}, {c.styling})")

    # Add prop detail
    for pr in bound_props:
        parts.append(f"featuring {pr.name} ({pr.description})")

    parts.append(preset.style_tokens)
    expanded_prompt_en = ", ".join(p for p in parts if p)

    return ResolvedPrompt(
        original_prompt=prompt,
        expanded_prompt_en=expanded_prompt_en,
        negative_prompt=preset.negative_prompt,
        effective_seed=effective_seed,
        bound_characters=bound_chars,
        bound_scenes=bound_scenes,
        bound_props=bound_props,
        ref_images=ref_images,
    )
