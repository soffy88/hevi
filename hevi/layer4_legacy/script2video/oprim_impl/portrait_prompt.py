"""角色三联画提示词模板。

3O 归属(待上游): `oprim.portrait_prompt`。
"""

from __future__ import annotations

from hevi.script2video.schemas import PortraitViewName

_FRONT_PROMPT_TEMPLATE = (
    "Generate a full-body, front-view portrait of character {identifier} based on "
    "the following description, with a pure white background. Use a wide 16:9 "
    "landscape canvas, not a vertical portrait canvas. The character should be "
    "centered in the image, occupying the middle of the wide frame with enough "
    "horizontal empty space. Gazing straight ahead. Standing with arms relaxed "
    "at sides. Natural expression. Features: {features}. Style: {style}."
)

_SIDE_PROMPT_TEMPLATE = (
    "Generate a full-body, side-view portrait of character {identifier} based on "
    "the provided front-view portrait, with a pure white background. Use a wide "
    "16:9 landscape canvas. The character should be centered, facing left, "
    "standing with arms relaxed at sides. Keep identity consistent with the "
    "reference image. Style: {style}."
)

_BACK_PROMPT_TEMPLATE = (
    "Generate a full-body, back-view portrait of character {identifier} based on "
    "the provided front-view portrait, with a pure white background. Use a wide "
    "16:9 landscape canvas. The character should be centered, facing away from "
    "the camera. No facial features should be visible. Keep identity consistent "
    "with the reference image. Style: {style}."
)

_TEMPLATES: dict[PortraitViewName, str] = {
    "front": _FRONT_PROMPT_TEMPLATE,
    "side": _SIDE_PROMPT_TEMPLATE,
    "back": _BACK_PROMPT_TEMPLATE,
}


def build_portrait_prompt(
    view: PortraitViewName,
    *,
    identifier: str,
    features: str,
    style: str,
) -> str:
    """按视角拼出文生图 / 图生图提示词。"""
    template = _TEMPLATES.get(view)
    if template is None:
        raise ValueError(f"unknown portrait view: {view}")
    return template.format(identifier=identifier, features=features, style=style)
