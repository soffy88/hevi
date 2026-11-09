"""Structured schema helpers for the ai_drama line.

The line is deliberately JSON-first: every stage writes one document that a
later stage can re-read and check.  No stage invents missing fields; a missing
required field is reported by ``hevi.ai_drama.rules`` as a blocker.

Document shapes (all plain dicts, JSON-serialisable):

``script``      episode script: characters, scenes, beats, dialogue kinds
``storyboard``  segments of 2-4 shots, each shot with camera/light/refs/sound
``assets``      image list with @图片N references and usage text
``edit``        EDL items, reaction overlays, subtitle styles, loudness target
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

ASPECTS = {"9:16", "16:9", "1:1"}
STYLES = {"live_action", "anime", "game_pov", "3d_cg", "ink"}
DIALOGUE_KINDS = {"said", "inner", "vo"}
SHOT_SIZES = ("大远景", "远景", "大全景", "全景", "中景", "中近景", "近景", "特写", "大特写")
SCENE_HEADER_RE = re.compile(r"^\s*\d+\s+\S.*\[(?:内|外)\]\s*\[(?:日|夜|晨|昏)\]\s*$")
PICTURE_REF_RE = re.compile(r"@图片(\d+)")


def header_for(scene: dict[str, Any], fallback_no: int = 1) -> str:
    """Return the scene heading: ``场号 场景名 [内/外] [日/夜]``."""
    no = int(scene.get("scene_no") or fallback_no)
    name = str(scene.get("name") or scene.get("location") or "场景").strip()
    where = str(scene.get("int_ext") or "内").strip()
    when = str(scene.get("day_night") or "日").strip()
    return f"{no} {name} [{where}] [{when}]"


def iter_dialogue(script: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    """Yield ``(scene_id, beat_id, line)`` for every script dialogue line."""
    for scene in script.get("scenes") or []:
        sid = str(scene.get("scene_id") or "")
        for beat in scene.get("beats") or []:
            bid = str(beat.get("beat_id") or "")
            for line in beat.get("dialogue") or []:
                if isinstance(line, dict):
                    yield sid, bid, line


def iter_shots(storyboard: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for segment in storyboard.get("segments") or []:
        yield from segment.get("shots") or []


def dialogue_chars(lines: Iterable[dict[str, Any]]) -> int:
    return sum(len(str(line.get("text") or "").strip()) for line in lines)


def estimate_seconds(text: str) -> float:
    """2 s per 10 Chinese characters, minimum 1 s (brief rule)."""
    n = len((text or "").strip())
    return max(1.0, n * 0.2)


def normalize_script(data: dict[str, Any]) -> dict[str, Any]:
    """Fill only structural defaults (ids/headers), never creative fields."""
    script = dict(data)
    script.setdefault("aspect", "9:16")
    script.setdefault("style", "live_action")
    script.setdefault("characters", [])
    script.setdefault("scenes", [])
    for i, scene in enumerate(script["scenes"], start=1):
        scene.setdefault("scene_no", i)
        scene.setdefault("scene_id", f"sc_{i:02d}")
        scene.setdefault("header", header_for(scene, i))
        scene.setdefault("beats", [])
        for j, beat in enumerate(scene["beats"], start=1):
            beat.setdefault("beat_id", f"{scene['scene_id']}_b{j:02d}")
            beat.setdefault("dialogue", [])
            beat.setdefault("action", [])
            for line in beat["dialogue"]:
                line.setdefault("kind", "said")
    return script


def normalize_storyboard(data: dict[str, Any]) -> dict[str, Any]:
    sb = dict(data)
    sb.setdefault("aspect", "9:16")
    sb.setdefault("style", "live_action")
    sb.setdefault("segments", [])
    for i, seg in enumerate(sb["segments"], start=1):
        seg.setdefault("segment_id", f"seg_{i:02d}")
        seg.setdefault("shots", [])
        for j, shot in enumerate(seg["shots"], start=1):
            shot.setdefault("shot_id", f"{seg['segment_id']}_s{j}")
            shot.setdefault("segment_id", seg["segment_id"])
            shot.setdefault("dialogue", [])
            shot.setdefault("refs", [])
            shot.setdefault("negatives", [])
            shot.setdefault("sound", seg.get("sound", ""))
    return sb


def collect_subtitles(storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Build subtitle rows from storyboard dialogue, copying text verbatim."""
    rows: list[dict[str, Any]] = []
    for shot in iter_shots(storyboard):
        for line in shot.get("dialogue") or []:
            text = str(line.get("text") or "")
            if not text.strip():
                continue
            rows.append(
                {
                    "shot_id": shot.get("shot_id"),
                    "speaker": line.get("speaker"),
                    "text": text,
                    "kind": line.get("kind", "said"),
                }
            )
    return rows


def ref_index(assets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(img.get("ref")): img for img in assets.get("images") or []}
