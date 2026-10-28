"""Segment assembly gate (``video.segment_assembly_gate``).

A 3-5 minute film is not one long generation call. It is scenes
broken into segments, segments broken into shots, and each segment
mapped to exactly one generation node. This gate checks that
arithmetic before anyone spends generation budget:

1. A scene holds shots. A shot is one spoken line (or one silent
   beat) with a planned duration.
2. A line longer than 20 content characters must be split at
   semantic pauses into consecutive shots by the same speaker;
   words are never deleted to make a line fit.
3. A segment holds as many consecutive shots as fit under the
   segment cap, which is the smaller of 15 seconds and the model
   limit. A single shot longer than the cap fails and names the
   shot: split it first, never trim it silently.
4. A segment's duration is the sum of its shots' durations, and
   one segment maps to exactly one generation node.
5. The plan converts to a spend-brake storyboard (one row per
   shot) and to a project-graph chain (one motion node per
   segment), so the cheap gates downstream can run on it.

Duration arithmetic follows the existing prompt-compiler
convention so the two gates cannot disagree: content characters
divided by 4 per second, plus 0.4 seconds per punctuation mark,
plus 1.0 second of head/tail margin per shot. Content characters
are characters that are not whitespace and not punctuation.

Method ideas borrowed, text self-written, from
HBAI-Ltd/Toonflow-app (MIT, verified against the repository
LICENSE file; the MIT licence covers that repository only, not
model services or generated material). No Toonflow text, code or
assets are copied here.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

MAX_SEGMENT_SEC = 15.0
CHARS_PER_SEC = 4.0
PAUSE_PER_PUNCT_S = 0.4
HEAD_TAIL_MARGIN_S = 1.0
MAX_LINE_CHARS = 20

_PUNCT = set(
    "，。！？；：、……·—-「」『』（）《》〈〉\"'“”‘’.…?!;:,"
)
_SPLIT_PUNCT = set("，。！？；")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _content_chars(text: str) -> int:
    return sum(1 for ch in str(text) if not ch.isspace() and ch not in _PUNCT)


def _punct_count(text: str) -> int:
    return sum(1 for ch in str(text) if ch in _PUNCT)


def estimate_shot_duration_s(text: str) -> float:
    """Planned duration for one shot's spoken line.

    Empty or silent text costs 0.0 seconds. Otherwise the
    estimate is content characters / 4 per second, plus 0.4
    seconds per punctuation mark, plus 1.0 second head/tail
    margin. The estimate is a planning floor, not a promise
    about how fast a voice actor or TTS voice will speak.
    """
    text = str(text or "").strip()
    if not text:
        return 0.0
    return (
        _content_chars(text) / CHARS_PER_SEC
        + PAUSE_PER_PUNCT_S * _punct_count(text)
        + HEAD_TAIL_MARGIN_S
    )


def split_long_line(text: str) -> list[str]:
    """Split a line over 20 content characters at semantic pauses.

    Pieces keep their punctuation, consecutive pieces stay in
    order, and joining the pieces (ignoring whitespace) returns
    the original line exactly, so splitting can never delete or
    rewrite a word. A chunk with no semantic pause inside it is
    hard-split at 20 content characters as a last resort.
    """
    text = str(text or "").strip()
    if _content_chars(text) <= MAX_LINE_CHARS:
        return [text] if text else []
    pieces: list[str] = []
    current = ""
    for ch in text:
        current += ch
        if ch in _SPLIT_PUNCT:
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    shots: list[str] = []
    for piece in pieces:
        while _content_chars(piece) > MAX_LINE_CHARS:
            cut = ""
            count = 0
            for ch in piece:
                cut += ch
                if ch not in _PUNCT and not ch.isspace():
                    count += 1
                if count >= MAX_LINE_CHARS:
                    break
            shots.append(cut)
            piece = piece[len(cut):]
        if piece:
            shots.append(piece)
    return shots


def _normalise_shot(raw: Any, scene_id: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CapabilityError(
            f"video.segment_assembly_gate: scene {scene_id!r} shot "
            f"{index} is not an object"
        )
    shot_id = raw.get("shot_id")
    if not isinstance(shot_id, str) or not shot_id:
        raise CapabilityError(
            f"video.segment_assembly_gate: scene {scene_id!r} shot "
            f"{index} has no shot_id"
        )
    text = str(raw.get("text", "") or "")
    duration = raw.get("duration_sec")
    if duration is None:
        duration = estimate_shot_duration_s(text)
    if not _is_num(duration) or float(duration) < 0:
        raise CapabilityError(
            f"video.segment_assembly_gate: shot {shot_id!r} duration "
            f"must be a non-negative number"
        )
    return {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "text": text,
        "duration_sec": round(float(duration), 3),
    }


def plan_segments(
    scenes: Any, *, model_max_sec: Any = MAX_SEGMENT_SEC
) -> dict[str, Any]:
    """Pack scenes' shots into capped segments, one node each.

    ``scenes`` is a list of ``{"scene_id": ..., "shots": [...]}``.
    The segment cap is the smaller of 15 seconds and
    ``model_max_sec``. A single shot over the cap fails and names
    the shot. Shots are packed greedily in order; a segment never
    spans a gap in shot order, and segment durations are sums of
    shot durations, never rounded down to fit.
    """
    if not _is_num(model_max_sec) or float(model_max_sec) <= 0:
        raise CapabilityError(
            "video.segment_assembly_gate: model_max_sec must be a "
            "positive number"
        )
    cap = min(MAX_SEGMENT_SEC, float(model_max_sec))
    if not isinstance(scenes, list) or not scenes:
        raise CapabilityError(
            "video.segment_assembly_gate: scenes must be a non-empty list"
        )
    shots: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scene in scenes:
        if not isinstance(scene, dict) or not scene.get("scene_id"):
            raise CapabilityError(
                "video.segment_assembly_gate: every scene needs a scene_id"
            )
        scene_shots = scene.get("shots")
        if not isinstance(scene_shots, list) or not scene_shots:
            raise CapabilityError(
                f"video.segment_assembly_gate: scene "
                f"{scene['scene_id']!r} has no shots"
            )
        for index, raw in enumerate(scene_shots):
            shot = _normalise_shot(raw, str(scene["scene_id"]), index)
            if shot["shot_id"] in seen:
                raise CapabilityError(
                    f"video.segment_assembly_gate: duplicate shot_id "
                    f"{shot['shot_id']!r}"
                )
            seen.add(shot["shot_id"])
            if shot["duration_sec"] > cap:
                raise CapabilityError(
                    f"video.segment_assembly_gate: shot "
                    f"{shot['shot_id']!r} runs "
                    f"{shot['duration_sec']}s, over the segment cap "
                    f"{cap}s; split it at a semantic pause first, "
                    f"never trim it to fit"
                )
            shots.append(shot)
    segments: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_sec = 0.0
    for shot in shots:
        if current and current_sec + shot["duration_sec"] > cap:
            segments.append(_finish_segment(segments, current, current_sec))
            current = []
            current_sec = 0.0
        current.append(shot)
        current_sec += shot["duration_sec"]
    if current:
        segments.append(_finish_segment(segments, current, current_sec))
    total = round(sum(s["duration_sec"] for s in segments), 3)
    return {
        "segments": segments,
        "segment_count": len(segments),
        "total_sec": total,
        "cap_sec": cap,
        "segment_count_minimum": math.ceil(total / cap) if total else 0,
        "generation_nodes": [s["generation_node"] for s in segments],
        "shots": shots,
    }


def _finish_segment(
    segments: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    duration: float,
) -> dict[str, Any]:
    segment_id = f"seg-{len(segments) + 1:02d}"
    return {
        "segment_id": segment_id,
        "generation_node": segment_id,
        "scene_ids": sorted({s["scene_id"] for s in shots}),
        "shot_ids": [s["shot_id"] for s in shots],
        "shots": shots,
        "duration_sec": round(duration, 3),
    }


def to_storyboard_rows(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """One spend-brake storyboard row per shot in plan order."""
    if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list):
        raise CapabilityError(
            "video.segment_assembly_gate: plan has no shots list"
        )
    rows = []
    segment_of: dict[str, str] = {}
    for segment in plan.get("segments", []):
        for shot_id in segment.get("shot_ids", []):
            segment_of[shot_id] = segment["segment_id"]
    for shot in plan["shots"]:
        rows.append({
            "shot_id": shot["shot_id"],
            "visual": shot["text"],
            "duration_sec": shot["duration_sec"],
            "segment_id": segment_of.get(shot["shot_id"]),
        })
    return rows


def to_project_graph(plan: dict[str, Any]) -> dict[str, Any]:
    """One motion node per segment, chained in segment order."""
    from hevi.capabilities import project_graph

    if not isinstance(plan, dict) or not isinstance(plan.get("segments"), list):
        raise CapabilityError(
            "video.segment_assembly_gate: plan has no segments list"
        )
    nodes = []
    previous = None
    for segment in plan["segments"]:
        node = {
            "node_id": segment["segment_id"],
            "type": "motion",
            "inputs": [] if previous is None else [previous],
            "params": {
                "duration_sec": segment["duration_sec"],
                "shot_ids": segment["shot_ids"],
                "generation_node": segment["generation_node"],
            },
            "artifact": None,
        }
        nodes.append(node)
        previous = segment["segment_id"]
    return project_graph.create_graph(nodes)


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    plan = plan_segments(
        params.get("scenes"),
        model_max_sec=params.get("model_max_sec", MAX_SEGMENT_SEC),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "segment_assembly_report.json"
    report_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "segment_count": plan["segment_count"],
            "total_sec": plan["total_sec"],
        },
    )


def register_segment_assembly_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.segment_assembly_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "scenes": {"type": "array"},
                    "model_max_sec": {"type": "number"},
                },
                "required": ["scenes"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Segment assembly gate for 3-5 minute films: scenes "
                "pack into segments capped at the smaller of 15 "
                "seconds and the model limit, lines over 20 content "
                "characters split at semantic pauses without "
                "deleting words, segment duration equals the sum "
                "of its shots, and one segment maps to exactly one "
                "generation node. Converts to spend-brake storyboard "
                "rows and a project-graph motion chain. Renders "
                "nothing itself."
            ),
            line="video",
        )
    )
    return ["video.segment_assembly_gate"]


register_segment_assembly_capabilities_once()
