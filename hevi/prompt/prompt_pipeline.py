"""hevi prompt engineering pipeline.

Chain:
  raw topic
    → inject_visual_style  (sync, appends style/lighting/camera descriptors)
    → adapt_prompt_for_provider  (async, prefix/suffix per provider rules)
    → engineered prompt string

hevi owns the top-level topic/style pre-processing.
M8's internal shot-level prompt generation is separate and untouched.
"""

from oprim.adapt_prompt_for_provider import adapt_prompt_for_provider
from oprim.inject_visual_style import inject_visual_style

from hevi.prompt.style_presets import get_style_preset

__all__ = ["HEVI_TO_OPRIM_PROVIDER", "engineer_prompt", "engineer_prompt_from_preset"]

# Map hevi provider names → oprim provider keys used by _PROVIDER_RULES.
HEVI_TO_OPRIM_PROVIDER: dict[str, str] = {
    "ltx2_cloud": "ltx2",
    "wan_cloud": "wan22",
}


async def engineer_prompt(
    *,
    raw_prompt: str,
    target_provider: str,
    style: str | None = None,
    lighting: str | None = None,
    camera: str | None = None,
    color_grade: str | None = None,
    negative_prompt: str = "",
) -> str:
    """Run the full prompt engineering chain for a single clip.

    Step 1 — inject_visual_style (sync): appends non-None style descriptors.
    Step 2 — adapt_prompt_for_provider (async): applies provider-specific
              prefix/suffix rules (ltx2 → ", cinematic, 4K"; wan22 → "电影级画质，…").

    Args:
        raw_prompt: User-supplied topic/description.
        target_provider: hevi provider name ("ltx2_cloud", "wan_cloud").
        style: Visual style descriptor (e.g. "educational clear").
        lighting: Lighting descriptor (e.g. "bright even").
        camera: Camera motion descriptor (e.g. "smooth pan").
        color_grade: Color grade descriptor (e.g. "warm tones").
        negative_prompt: Negative prompt passed through to provider adapter.

    Returns:
        Engineered prompt string ready for the video generation API.
    """
    # Step 1: visual style injection (sync pure function)
    styled = inject_visual_style(
        raw_prompt,
        style=style,
        lighting=lighting,
        color_grade=color_grade,
        camera=camera,
    )

    # Step 2: provider adaptation (async)
    oprim_provider = HEVI_TO_OPRIM_PROVIDER.get(target_provider, target_provider)
    result: dict[str, str] = await adapt_prompt_for_provider(
        styled,
        provider=oprim_provider,
        negative_prompt=negative_prompt,
    )
    return result["prompt"]


async def engineer_prompt_from_preset(
    *,
    raw_prompt: str,
    target_provider: str,
    preset_name: str | None = None,
    style: str | None = None,
    lighting: str | None = None,
    camera: str | None = None,
    color_grade: str | None = None,
    negative_prompt: str = "",
) -> str:
    """engineer_prompt with optional style-preset shortcut.

    If ``preset_name`` is given, its values override individual style params.
    Individual params (style/lighting/camera/color_grade) are used otherwise.
    """
    if preset_name is not None:
        preset = get_style_preset(preset_name)
        return await engineer_prompt(
            raw_prompt=raw_prompt,
            target_provider=target_provider,
            style=preset.get("style"),
            lighting=preset.get("lighting"),
            camera=preset.get("camera"),
            color_grade=preset.get("color_grade"),
            negative_prompt=negative_prompt,
        )
    return await engineer_prompt(
        raw_prompt=raw_prompt,
        target_provider=target_provider,
        style=style,
        lighting=lighting,
        camera=camera,
        color_grade=color_grade,
        negative_prompt=negative_prompt,
    )


async def engineer_prompt_pair_from_preset(
    *,
    raw_prompt: str,
    target_provider: str,
    preset_name: str | None = None,
    style: str | None = None,
    lighting: str | None = None,
    camera: str | None = None,
    color_grade: str | None = None,
    negative_prompt: str = "",
) -> tuple[str, str]:
    """同 engineer_prompt_from_preset,但返回 (正向, 负向) 二元组。

    RFC-002 item 8: 旧 engineer_prompt 只返回 result["prompt"],丢弃了
    adapt_prompt_for_provider 算出的负向。此函数保留负向,供接受负向的 provider
    (wan_local)逐镜头下发;云 provider API 暂无原生负向参数(provider 层支持后接线)。
    """
    sp = get_style_preset(preset_name) if preset_name is not None else {}
    styled = inject_visual_style(
        raw_prompt,
        style=sp.get("style", style),
        lighting=sp.get("lighting", lighting),
        color_grade=sp.get("color_grade", color_grade),
        camera=sp.get("camera", camera),
    )
    oprim_provider = HEVI_TO_OPRIM_PROVIDER.get(target_provider, target_provider)
    # 合并预设负向(item 12 起预设带 negative)与调用方负向
    merged_neg = ", ".join(s for s in (sp.get("negative", ""), negative_prompt) if s)
    result: dict[str, str] = await adapt_prompt_for_provider(
        styled, provider=oprim_provider, negative_prompt=merged_neg,
    )
    return result["prompt"], result.get("negative_prompt", merged_neg)
