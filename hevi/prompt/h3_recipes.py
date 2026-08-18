"""Optional H3 camera-word + recipe must-phrase lint.

Not a second storyboard engine. Empty camera / no recipe → skip.
Suggested size/move from a card is never a hard gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# MiniMax H3 official camera-move domain (20). Completeness is the point.
H3_CAMERA_MOVES: tuple[str, ...] = (
    "Static",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "Truck Left",
    "Truck Right",
    "Pedestal Up",
    "Pedestal Down",
    "Zoom In",
    "Zoom Out",
    "Dolly In",
    "Dolly Out",
    "Roll CW",
    "Roll CCW",
    "Follow",
    "Shake",
    "Orbit",
    "Handheld",
    "Tracking",
)

# Angle-only words are not movement claims; do not fail them.
_ANGLE_ONLY = ("平视", "仰拍", "俯拍", "正面", "侧面", "背面", "侧45", "环绕")

_ALIAS_TO_OFFICIAL: dict[str, str] = {
    "固定": "Static",
    "静止": "Static",
    "左摇": "Pan Left",
    "右摇": "Pan Right",
    "上摇": "Tilt Up",
    "下摇": "Tilt Down",
    "左移": "Truck Left",
    "右移": "Truck Right",
    "升起": "Pedestal Up",
    "下降": "Pedestal Down",
    "推进": "Dolly In",
    "推镜": "Dolly In",
    "拉镜": "Dolly Out",
    "拉远": "Dolly Out",
    "推近": "Zoom In",
    "拉近": "Zoom In",
    "跟拍": "Follow",
    "跟随": "Follow",
    "手持": "Handheld",
    "抖动": "Shake",
    "环绕运镜": "Orbit",
    "顺时针滚": "Roll CW",
    "逆时针滚": "Roll CCW",
}


@dataclass(frozen=True)
class RecipeCard:
    recipe_id: str
    must_phrases: tuple[str, ...] = ()
    min_cuts: int = 1


def normalize_camera(raw: str) -> str:
    return " ".join((raw or "").strip().split())


def resolve_h3_camera(raw: str) -> str | None:
    """Official English token if the field claims a known move, else None."""
    text = normalize_camera(raw)
    if not text:
        return None
    lower = text.lower()
    for official in H3_CAMERA_MOVES:
        if official.lower() in lower:
            return official
    for alias, official in _ALIAS_TO_OFFICIAL.items():
        if alias in text:
            return official
    return None


def is_angle_only(raw: str) -> bool:
    text = normalize_camera(raw)
    if not text:
        return False
    return any(tok in text for tok in _ANGLE_ONLY) and resolve_h3_camera(text) is None


def camera_in_official_set(raw: str) -> bool:
    if not normalize_camera(raw):
        return True
    if is_angle_only(raw):
        return True
    return resolve_h3_camera(raw) is not None


def phrases_present(haystack: str, phrases: tuple[str, ...] | list[str]) -> list[str]:
    blob = (haystack or "").lower()
    missing: list[str] = []
    for phrase in phrases:
        token = str(phrase or "").strip().lower()
        if len(token) < 6:
            continue
        if token not in blob:
            missing.append(phrase)
    return missing


def lint_h3_camera(shots: list[Any]) -> list[tuple[str, str, str]]:
    """Return (rule, shot_id, message) for unknown movement claims."""
    out: list[tuple[str, str, str]] = []
    for shot in shots:
        camera = getattr(shot, "camera", "") or ""
        shot_id = str(getattr(shot, "shot_id", "") or "?")
        if not normalize_camera(camera) or is_angle_only(camera):
            continue
        if not camera_in_official_set(camera):
            out.append(
                (
                    "C1",
                    shot_id,
                    f"{shot_id} 运镜「{camera}」不在 H3 官方 20 词表",
                )
            )
    return out


def lint_recipes(
    shots: list[Any],
    cards: dict[str, RecipeCard] | None,
) -> list[tuple[str, str, str]]:
    """Optional. cards is None → skip (not a silent pass with a fake ok)."""
    if cards is None:
        return []
    out: list[tuple[str, str, str]] = []
    for shot in shots:
        recipe = str(getattr(shot, "recipe", "") or "").strip()
        if not recipe:
            continue
        shot_id = str(getattr(shot, "shot_id", "") or "?")
        card = cards.get(recipe)
        if card is None:
            out.append(("R1", shot_id, f"{shot_id} 配方 {recipe} 不在卡库"))
            continue
        frame = str(getattr(shot, "visual_prompt", "") or "")
        missing = phrases_present(frame, card.must_phrases)
        if missing:
            out.append(
                (
                    "R2",
                    shot_id,
                    f"{shot_id} 缺少配方必备短语: {', '.join(missing)}",
                )
            )
    return out
