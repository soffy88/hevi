"""参考图挑选的纯函数:视角、下标、prompt 前缀。

3O 归属(待上游): `oprim.reference_pick`。
朝向几何与 director.scene_stage.resolve_subject_view 同约定,但本层不引用 director。
"""

from __future__ import annotations

from hevi.script2video.schemas import PortraitViewName, ReferenceCandidate

_VIEW_BY_DELTA = ("front", "right", "back", "left")
_FACING_ALIASES: dict[str, PortraitViewName] = {
    "front": "front",
    "正面": "front",
    "面向镜头": "front",
    "side": "side",
    "侧面": "side",
    "侧对": "side",
    "profile": "side",
    "back": "back",
    "背面": "back",
    "背对": "back",
    "背后": "back",
}


def pick_portrait_view(
    *,
    facing_text: str = "",
    cam_azimuth_deg: float | None = None,
    char_facing_deg: float | None = None,
) -> PortraitViewName:
    """选正/侧/背。角度齐全时走 90° 量化;否则扫朝向文本;再否则正面(身份最强)。"""
    if cam_azimuth_deg is not None and char_facing_deg is not None:
        delta = round(((cam_azimuth_deg - char_facing_deg) % 360) / 90) % 4
        mapped = _VIEW_BY_DELTA[delta]
        return "side" if mapped in {"left", "right"} else mapped  # type: ignore[return-value]
    blob = facing_text.strip().lower()
    for key, view in _FACING_ALIASES.items():
        if key in blob:
            return view
    return "front"


def select_pairs_by_indices(
    pairs: list[tuple[str, str]],
    indices: list[int],
) -> list[tuple[str, str]]:
    """按 LLM/规则下标取参考图。拒绝负数与越界(Python 负索引会静默拿错图)。"""
    invalid = [idx for idx in indices if idx < 0 or idx >= len(pairs)]
    if invalid:
        raise ValueError(f"ref_image_indices out of range: {invalid} (have {len(pairs)} images)")
    return [pairs[idx] for idx in indices]


def compose_image_prefix_prompt(pairs: list[tuple[str, str]]) -> str:
    lines = [f"Image {idx}: {text}" for idx, (_path, text) in enumerate(pairs)]
    return "\n".join(lines)


def cap_refs(candidates: list[ReferenceCandidate], *, limit: int = 8) -> list[ReferenceCandidate]:
    return candidates[: max(0, limit)]
