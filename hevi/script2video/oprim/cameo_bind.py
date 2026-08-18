"""AutoCameo 原子:照片→角色标识、默认人设、定位。

3O 归属(待上游): `oprim.cameo_bind`。
"""

from __future__ import annotations

from pathlib import Path

from hevi.script2video.adapter_schemas import CameoRole
from hevi.script2video.oprim.idea_parse import photo_stem_name, slugify

_PROTAGONIST_HINTS = ("主角", "protagonist", "我", "我的", "本人", "pet", "宠物")


def cameo_identifier(name: str, *, index: int = 0) -> str:
    return slugify(name) or f"cameo_{index}"


def default_description(name: str, photo: Path) -> str:
    return (
        f"{name} from reference photo {photo.name}. "
        "Preserve facial identity, hairstyle, and body proportions from the photo."
    )


def choose_role(story_context: str, *, index: int) -> CameoRole:
    blob = (story_context or "").lower()
    if index == 0 and any(hint.lower() in blob for hint in _PROTAGONIST_HINTS):
        return "protagonist"
    if index == 0 and not blob.strip():
        return "protagonist"
    if "旁白" in blob or "narrator" in blob:
        return "narrator"
    if index == 0:
        return "supporting"
    return "cameo"


def display_name_from_photo(photo: Path) -> str:
    return photo_stem_name(str(photo))
