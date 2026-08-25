"""五层镜头提示词构建 —— 结构化 shot_language → provider 优化英文 prompt。

对标 OpenMontage lib/shot_prompt_builder.py(3O 内化):
旧做法是给每个场景描述前置一段固定 playbook 前缀, 导致所有镜头同质。
本模块按职业电影摄影提示词研究拆 5 层, 逐层可空、逐层拼接:

  Layer 1 Camera   —— 镜头焦距 + 景深
  Layer 2 Movement —— 景别 + 运镜
  Layer 3 Subject  —— 场景描述 + 材质关键词
  Layer 4 Lighting —— 布光基调 + 色温
  Layer 5 Style    —— 从 playbook 提取审美(非逐字前缀)

与 hevi/studio/craft.py 的 compile_shot_spec(中文五面词)关系:
那是**中文**制片层五面(主体/动作/场景/空间/机位), 面向人/中文 provider;
这里是**英文** provider 优化层(英文短语表 + 结构化 shot_language),
面向 veo3 / wan / kling / seedance 等英文提示词视频模型。两者互补。

全部为纯函数, 零依赖。
"""

from __future__ import annotations

from typing import Any

# 景别 → 英文短语
_SHOT_SIZE_PHRASES = {
    "extreme_wide": "extreme wide shot showing vast environment",
    "wide": "wide shot capturing full scene",
    "medium_wide": "medium-wide shot framing subject with surroundings",
    "medium": "medium shot from waist up",
    "medium_close": "medium close-up from chest up",
    "close_up": "close-up focusing on face or detail",
    "extreme_close_up": "extreme close-up on fine detail",
    "over_shoulder": "over-the-shoulder perspective",
    "insert": "insert shot of specific detail",
    "establishing": "establishing shot setting the location",
}

# 运镜 → 英文短语
_MOVEMENT_PHRASES = {
    "static": "locked-off static camera",
    "pan_left": "smooth pan to the left",
    "pan_right": "smooth pan to the right",
    "tilt_up": "gentle tilt upward",
    "tilt_down": "gentle tilt downward",
    "dolly_in": "slow dolly in toward subject",
    "dolly_out": "slow dolly out from subject",
    "tracking_left": "tracking shot moving left alongside subject",
    "tracking_right": "tracking shot moving right alongside subject",
    "crane_up": "crane shot rising upward",
    "crane_down": "crane shot descending",
    "handheld": "handheld camera with natural movement",
    "steadicam": "smooth steadicam following movement",
    "whip_pan": "fast whip pan",
    "orbital": "orbital camera circling subject",
    "zoom_in": "slow zoom in",
    "zoom_out": "slow zoom out",
    "rack_focus": "rack focus shift between foreground and background",
}

# 布光基调 → 英文短语
_LIGHTING_PHRASES = {
    "high_key": "bright high-key lighting, minimal shadows",
    "low_key": "dramatic low-key lighting with deep shadows",
    "natural": "natural ambient lighting",
    "golden_hour": "warm golden hour sunlight",
    "blue_hour": "cool blue hour twilight",
    "tungsten_warm": "warm tungsten interior lighting",
    "neon": "neon-lit with vibrant color spill",
    "silhouette": "backlit silhouette",
    "rim_lit": "rim lighting highlighting edges",
    "volumetric": "volumetric light with visible rays",
    "overcast_soft": "soft overcast diffused light",
}

# 景深 → 英文短语
_DOF_PHRASES = {
    "shallow": "shallow depth of field with bokeh",
    "medium": "medium depth of field",
    "deep": "deep focus with everything sharp",
}

# 色温 → 英文短语
_COLOR_TEMP_PHRASES = {
    "cool": "cool blue-toned color palette",
    "neutral": "neutral balanced colors",
    "warm": "warm amber-toned color palette",
    "mixed": "mixed color temperatures for contrast",
}

# 不参与生成 prompt 的场景类型(转场等)
_SKIP_SCENE_TYPES = frozenset({"transition"})


def build_shot_prompt(
    scene: dict[str, Any],
    style_context: dict[str, Any] | None = None,
) -> str:
    """把带结构化 shot_language 的场景转成生成 prompt。

    Args:
        scene: 场景 dict(需含 shot_language / description / texture_keywords)。
        style_context: 可选 playbook 风格信息, 键 'mood' / 'visual_language.aesthetic'。

    Returns:
        自然语言 prompt(英文, provider 优化)。层间用 ". " 拼接, 空层自动跳过。
    """
    sl = scene.get("shot_language", {}) or {}
    layers: list[str] = []

    # Layer 1: Camera —— 焦距 + 景深
    camera_parts: list[str] = []
    if sl.get("lens_mm"):
        camera_parts.append(f"{sl['lens_mm']}mm lens")
    if sl.get("depth_of_field"):
        camera_parts.append(_DOF_PHRASES.get(sl["depth_of_field"], str(sl["depth_of_field"])))
    if camera_parts:
        layers.append(", ".join(p for p in camera_parts if p))

    # Layer 2: Movement —— 景别 + 运镜
    movement_parts: list[str] = []
    if sl.get("shot_size"):
        movement_parts.append(_SHOT_SIZE_PHRASES.get(sl["shot_size"], str(sl["shot_size"])))
    if sl.get("camera_movement") and sl["camera_movement"] != "static":
        movement_parts.append(
            _MOVEMENT_PHRASES.get(sl["camera_movement"], str(sl["camera_movement"]))
        )
    if movement_parts:
        layers.append(", ".join(movement_parts))

    # Layer 3: Subject —— 场景描述 + 材质关键词
    description = str(scene.get("description") or "")
    texture = scene.get("texture_keywords") or []
    subject_parts = [description]
    if texture:
        if isinstance(texture, (list, tuple)):
            subject_parts.append(", ".join(str(t) for t in texture))
        else:
            subject_parts.append(str(texture))
    subject_text = ". ".join(p for p in subject_parts if p)
    if subject_text:
        layers.append(subject_text)

    # Layer 4: Lighting —— 布光 + 色温
    lighting_parts: list[str] = []
    if sl.get("lighting_key"):
        lighting_parts.append(_LIGHTING_PHRASES.get(sl["lighting_key"], str(sl["lighting_key"])))
    if sl.get("color_temperature"):
        lighting_parts.append(
            _COLOR_TEMP_PHRASES.get(sl["color_temperature"], str(sl["color_temperature"]))
        )
    if lighting_parts:
        layers.append(", ".join(p for p in lighting_parts if p))

    # Layer 5: Style —— 从 playbook 提取(非逐字前缀)
    if style_context:
        mood = style_context.get("mood", "") or ""
        visual_lang = style_context.get("visual_language", {}) or {}
        style_hint = (visual_lang.get("aesthetic") or mood) or ""
        if style_hint:
            layers.append(f"Style: {style_hint}")

    return ". ".join(layers)


def build_batch_prompts(
    scenes: list[dict[str, Any]],
    style_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """为场景计划里所有视觉场景批量构建 prompt。

    Returns: [{scene_id, prompt, hero_moment}, ...]。
    转场等非视觉场景跳过。
    """
    results: list[dict[str, Any]] = []
    for scene in scenes:
        if scene.get("type") in _SKIP_SCENE_TYPES:
            continue
        prompt = build_shot_prompt(scene, style_context)
        results.append(
            {
                "scene_id": str(scene.get("id") or scene.get("scene_id") or "unknown"),
                "prompt": prompt,
                "hero_moment": bool(scene.get("hero_moment", False)),
            }
        )
    return results


__all__ = [
    "_LIGHTING_PHRASES",
    "_MOVEMENT_PHRASES",
    "_SHOT_SIZE_PHRASES",
    "build_batch_prompts",
    "build_shot_prompt",
]
