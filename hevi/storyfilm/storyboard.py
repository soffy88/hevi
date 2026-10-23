"""Structured storyboard layer for the storyfilm line.

Design borrowed from AID Studio's storyboard model (MIT; re-implemented
for this pipeline — see ``~/workspace/references/aid-studio/LEARN.md``):

  * a shot is more than narration + a free-text visual: it carries a
    structured parameter block (shot size / camera angle / camera
    movement / transition), the scene it belongs to, the cast it shows
    and a pre-production duration estimate;
  * beats are grouped into scenes (场次) — the flat beat list gains a
    scene table and every beat points back at its scene;
  * the duration estimate is a *plan* value only.  This line measures
    the real timing from word-level audio alignment after narration;
    the plan exists so a storyboard can be reviewed before render time
    is spent, and so plan-vs-actual stays visible in the shot table.

The story LLM contract gained optional per-beat fields (``scene`` /
``shot_size`` / ``camera_angle`` / ``characters``).  Whatever a draft
omits is derived deterministically from the fields every draft already
guarantees (visual_en / motion_prompt / narration), so drafts written
before this layer — and the existing test-suite — keep working
unchanged.  Everything in this module is pure.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Plan-time speech rate in narration characters per second.  Mirrors
# pipeline.SPEECH_CHARS_PER_SEC (same pilot measurement); duplicated so
# this module stays dependency-free (pipeline imports this module).
EST_CHARS_PER_SEC = 6.32
EST_TAIL_S = 0.9  # planned pause after a beat (cf. pipeline tail rules)

SHOT_SIZES = (
    "extreme_wide",
    "wide",
    "full",
    "medium",
    "medium_close_up",
    "close_up",
    "extreme_close_up",
)
CAMERA_ANGLES = (
    "eye_level",
    "low_angle",
    "high_angle",
    "overhead",
    "dutch_angle",
)
CAMERA_MOVEMENTS = (
    "static",
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
)
TRANSITIONS = ("cut", "fade_in", "fade_out", "dissolve")

_SIZE_ALIASES = {
    "extreme wide": "extreme_wide",
    "extreme wide shot": "extreme_wide",
    "大远景": "extreme_wide",
    "远景": "extreme_wide",
    "wide": "wide",
    "wide shot": "wide",
    "establishing": "wide",
    "establishing shot": "wide",
    "全景": "wide",
    "full": "full",
    "full shot": "full",
    "全身": "full",
    "medium": "medium",
    "medium shot": "medium",
    "中景": "medium",
    "medium close up": "medium_close_up",
    "medium closeup": "medium_close_up",
    "mcu": "medium_close_up",
    "中近景": "medium_close_up",
    "近景": "medium_close_up",
    "close up": "close_up",
    "closeup": "close_up",
    "cu": "close_up",
    "特写": "close_up",
    "extreme close up": "extreme_close_up",
    "extreme closeup": "extreme_close_up",
    "ecu": "extreme_close_up",
    "大特写": "extreme_close_up",
}

_ANGLE_ALIASES = {
    "eye level": "eye_level",
    "eyelevel": "eye_level",
    "平视": "eye_level",
    "low angle": "low_angle",
    "仰拍": "low_angle",
    "仰视": "low_angle",
    "high angle": "high_angle",
    "俯拍": "high_angle",
    "俯视": "high_angle",
    "overhead": "overhead",
    "top down": "overhead",
    "topdown": "overhead",
    "aerial": "overhead",
    "bird s eye": "overhead",
    "birds eye": "overhead",
    "航拍": "overhead",
    "鸟瞰": "overhead",
    "dutch": "dutch_angle",
    "dutch angle": "dutch_angle",
    "倾斜": "dutch_angle",
}

_MOVEMENT_ALIASES = {
    "static": "static",
    "locked": "static",
    "fixed": "static",
    "固定": "static",
    "静止": "static",
    "push in": "push_in",
    "pushin": "push_in",
    "zoom in": "push_in",
    "dolly in": "push_in",
    "推镜": "push_in",
    "推进": "push_in",
    "pull out": "pull_out",
    "pullout": "pull_out",
    "zoom out": "pull_out",
    "dolly out": "pull_out",
    "拉镜": "pull_out",
    "拉远": "pull_out",
    "pan left": "pan_left",
    "左摇": "pan_left",
    "pan right": "pan_right",
    "右摇": "pan_right",
    "pan": "pan_right",
    "摇镜": "pan_right",
    "tilt up": "tilt_up",
    "上摇": "tilt_up",
    "tilt down": "tilt_down",
    "下摇": "tilt_down",
}

_TRANSITION_ALIASES = {
    "cut": "cut",
    "硬切": "cut",
    "fade in": "fade_in",
    "淡入": "fade_in",
    "fade out": "fade_out",
    "淡出": "fade_out",
    "dissolve": "dissolve",
    "cross dissolve": "dissolve",
    "叠化": "dissolve",
    "fade": "dissolve",
    "淡化": "dissolve",
}


def _norm_key(value: Any) -> str:
    """Loose lookup key: NFKC, lowercase, separators collapsed."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).strip().lower()
    text = re.sub(r"[\s\-_]+", " ", text)
    return text.strip()


def _lookup(value: Any, aliases: dict[str, str], canonical: tuple[str, ...]) -> str | None:
    key = _norm_key(value)
    if not key:
        return None
    if key.replace(" ", "_") in canonical:
        return key.replace(" ", "_")
    return aliases.get(key)


def normalize_shot_size(value: Any) -> str | None:
    return _lookup(value, _SIZE_ALIASES, SHOT_SIZES)


def normalize_camera_angle(value: Any) -> str | None:
    return _lookup(value, _ANGLE_ALIASES, CAMERA_ANGLES)


def normalize_camera_movement(value: Any) -> str | None:
    return _lookup(value, _MOVEMENT_ALIASES, CAMERA_MOVEMENTS)


def normalize_transition(value: Any) -> str | None:
    return _lookup(value, _TRANSITION_ALIASES, TRANSITIONS)


def derive_shot_size(visual_en: str, motion_prompt: str) -> str:
    """Deterministic shot-size guess from the free-text fields."""
    hay = f"{visual_en} {motion_prompt}".lower()
    if "extreme close" in hay:
        return "extreme_close_up"
    if "close-up" in hay or "closeup" in hay or "close up" in hay:
        return "close_up"
    if "aerial" in hay or "vast" in hay or "panorama" in hay:
        return "extreme_wide"
    if "wide shot" in hay or "establishing" in hay or "landscape" in hay:
        return "wide"
    if "medium" in hay:
        return "medium"
    if "face" in hay or "expression" in hay or "eyes" in hay:
        return "medium_close_up"
    return "medium"


def derive_camera_angle(visual_en: str) -> str:
    hay = visual_en.lower()
    if "aerial" in hay or "from above" in hay or "overhead" in hay or "bird" in hay:
        return "overhead"
    if "low angle" in hay or "looking up" in hay or "from below" in hay:
        return "low_angle"
    if "high angle" in hay or "looking down" in hay:
        return "high_angle"
    return "eye_level"


def derive_camera_movement(motion_prompt: str, *, index: int) -> str:
    """Canonical movement from the free-text motion prompt.

    Mirrors the intent of pipeline.ken_burns_params (which stays the
    render-time authority); this is the *planned* movement recorded on
    the storyboard.
    """
    text = (motion_prompt or "").lower()
    explicit = normalize_camera_movement(text)
    if explicit and explicit != "pan_right":
        return explicit
    if "pan left" in text:
        return "pan_left"
    if "pan" in text or "track" in text or "follow" in text:
        return "pan_left" if index % 2 else "pan_right"
    if "pull" in text or "zoom out" in text or "reveal" in text:
        return "pull_out"
    if "static" in text or "still" in text:
        return "static"
    if "push" in text or "zoom" in text or "close" in text or "in" in text:
        return "push_in"
    return ("push_in", "pan_right", "pull_out", "pan_left")[index % 4]


def estimate_beat_seconds(narration: str) -> float:
    """Pre-production duration estimate for one beat."""
    return round(len(narration or "") / EST_CHARS_PER_SEC + EST_TAIL_S, 2)


# Scene-name fallback labels for beats that carry no scene field.
_SCENE_LABELS = (
    (("pond", "lake", "池塘"), "池塘边"),
    (("river", "stream", "河"), "河边"),
    (("bridge", "桥"), "小桥上"),
    (("forest", "woods", "tree", "林"), "林间"),
    (("meadow", "field", "grass", "草地"), "草地上"),
    (("village", "street", "村"), "村庄里"),
    (("home", "house", "room", "家"), "家中"),
    (("night sky", "stars", "moon", "夜空"), "夜空下"),
    (("rain", "雨"), "雨中"),
)


def _fallback_scene_name(beat: dict[str, Any], ordinal: int) -> str:
    hay = f"{beat.get('visual_en', '')} {beat.get('narration', '')}".lower()
    for keys, label in _SCENE_LABELS:
        if any(k in hay for k in keys):
            return label
    return f"场景{ordinal}"


def segment_scenes(beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group consecutive beats into scenes (场次).

    Beats with an explicit ``scene`` name group by that name while
    consecutive; a beat without one joins the open scene when there is
    one, otherwise starts a fallback-named scene.  Returns scene dicts
    with ``scene_id`` (SC01…), ``name``, ``beat_indexes`` and the first
    beat's visual description.
    """
    scenes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_key: str | None = None
    for i, beat in enumerate(beats):
        name = beat.get("scene")
        name = name.strip() if isinstance(name, str) and name.strip() else None
        if name is not None:
            key = f"named:{name}"
            if current is None or key != current_key:
                current = {
                    "scene_id": f"SC{len(scenes) + 1:02d}",
                    "name": name,
                    "beat_indexes": [],
                    "description_en": str(beat.get("visual_en") or ""),
                }
                scenes.append(current)
                current_key = key
        elif current is None:
            current = {
                "scene_id": f"SC{len(scenes) + 1:02d}",
                "name": _fallback_scene_name(beat, len(scenes) + 1),
                "beat_indexes": [],
                "description_en": str(beat.get("visual_en") or ""),
            }
            scenes.append(current)
            current_key = f"auto:{id(current)}"
        current["beat_indexes"].append(i)
    for scene in scenes:
        scene["beat_count"] = len(scene["beat_indexes"])
    return scenes


def _name_key(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return unicodedata.normalize("NFKC", name).strip().lower()


def enrich_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *draft* with the structured storyboard fields.

    Adds the scene table (``scenes``) and, per beat: ``scene_ref`` /
    ``scene_name``, ``shot_size``, ``camera_angle``, ``camera_movement``,
    ``transition``, ``est_duration_s``, ``character_refs`` (cast names
    resolved against the draft's character list), ``narrative_function``.
    Explicit draft values win; missing ones are derived.  The input
    draft is not mutated.
    """
    beats = [dict(b) for b in draft.get("beats") or []]
    characters = draft.get("characters") or []
    by_key: dict[str, str] = {}
    for char in characters:
        cname = char.get("name") if isinstance(char, dict) else None
        if isinstance(cname, str) and cname.strip():
            by_key[_name_key(cname)] = cname.strip()
            for alias in char.get("aliases") or []:
                if isinstance(alias, str) and alias.strip():
                    by_key.setdefault(_name_key(alias), cname.strip())

    scenes = segment_scenes(beats)
    scene_of: dict[int, dict[str, Any]] = {}
    for scene in scenes:
        for idx in scene["beat_indexes"]:
            scene_of[idx] = scene

    total = len(beats)
    for i, beat in enumerate(beats):
        scene = scene_of.get(i)
        if scene:
            beat["scene_ref"] = scene["scene_id"]
            beat["scene_name"] = scene["name"]
        beat["shot_size"] = normalize_shot_size(beat.get("shot_size")) or derive_shot_size(
            str(beat.get("visual_en") or ""), str(beat.get("motion_prompt") or "")
        )
        beat["camera_angle"] = normalize_camera_angle(
            beat.get("camera_angle")
        ) or derive_camera_angle(str(beat.get("visual_en") or ""))
        beat["camera_movement"] = normalize_camera_movement(
            beat.get("camera_movement")
        ) or derive_camera_movement(str(beat.get("motion_prompt") or ""), index=i)
        beat["transition"] = (
            "fade_in"
            if i == 0
            else normalize_transition(beat.get("transition")) or "cut"
        )
        beat["est_duration_s"] = estimate_beat_seconds(str(beat.get("narration") or ""))
        refs: list[str] = []
        unresolved: list[str] = []
        for raw_name in beat.get("characters") or []:
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            canonical = by_key.get(_name_key(raw_name))
            if canonical:
                if canonical not in refs:
                    refs.append(canonical)
            elif raw_name.strip() not in unresolved:
                unresolved.append(raw_name.strip())
        beat["character_refs"] = refs
        if unresolved:
            beat["character_names_unresolved"] = unresolved
        function = beat.get("narrative_function")
        if not (isinstance(function, str) and function.strip()):
            if i == 0:
                function = "hook"
            elif i == total - 1 and total > 1:
                function = "resolution"
            else:
                function = "development"
            beat["narrative_function"] = function.strip()

    out = dict(draft)
    out["beats"] = beats
    out["scenes"] = scenes
    out["storyboard_version"] = 1
    return out


def storyboard_rows(
    draft: dict[str, Any], shots: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """One flat row per beat: plan fields + measured timing when given."""
    rows: list[dict[str, Any]] = []
    beats = draft.get("beats") or []
    for i, beat in enumerate(beats):
        shot = shots[i] if shots and i < len(shots) else {}
        rows.append(
            {
                "shot_no": i + 1,
                "scene_ref": beat.get("scene_ref") or shot.get("scene_ref") or "",
                "scene_name": beat.get("scene_name") or shot.get("scene_name") or "",
                "narration": beat.get("narration") or shot.get("narration") or "",
                "shot_size": beat.get("shot_size") or shot.get("shot_size") or "",
                "camera_angle": beat.get("camera_angle") or shot.get("camera_angle") or "",
                "camera_movement": beat.get("camera_movement")
                or shot.get("camera_movement")
                or "",
                "character_refs": list(
                    beat.get("character_refs") or shot.get("character_refs") or []
                ),
                "transition": beat.get("transition") or shot.get("transition") or "",
                "est_duration_s": beat.get("est_duration_s")
                if beat.get("est_duration_s") is not None
                else shot.get("est_duration_s"),
                "duration_s": shot.get("duration_s"),
                "image": shot.get("image") or shot.get("first_frame") or "",
            }
        )
    return rows


def _cell(text: Any, limit: int = 42) -> str:
    value = str(text or "").replace("|", "｜").replace("\n", " ").strip()
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    return value or "—"


def storyboard_markdown(
    draft: dict[str, Any], shots: list[dict[str, Any]] | None = None
) -> str:
    """Human-readable structured storyboard （分镜表） for a job folder."""
    title = str(draft.get("title") or "未命名")
    lines = [f"# 分镜表 · 《{title}》", ""]
    scenes = draft.get("scenes") or []
    if scenes:
        lines += ["## 场次", "", "| 场次 | 名称 | 镜头数 | 场景描述 |", "|---|---|---|---|"]
        for scene in scenes:
            beats = ", ".join(str(i + 1) for i in scene.get("beat_indexes") or [])
            lines.append(
                f"| {scene.get('scene_id', '')} | {_cell(scene.get('name'), 20)} "
                f"| {scene.get('beat_count', 0)}（镜 {beats}） "
                f"| {_cell(scene.get('description_en'), 60)} |"
            )
        lines.append("")
    lines += [
        "## 镜头",
        "",
        "| 镜号 | 场次 | 景别 | 机位 | 运镜 | 时长 估/实(s) | 出场角色 | 转场 | 旁白 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in storyboard_rows(draft, shots):
        est = row.get("est_duration_s")
        real = row.get("duration_s")
        timing = f"{est if est is not None else '—'}/{real if real is not None else '—'}"
        cast = "、".join(row["character_refs"]) if row["character_refs"] else "—"
        lines.append(
            f"| {row['shot_no']} | {row['scene_ref']} {_cell(row['scene_name'], 12)} "
            f"| {row['shot_size']} | {row['camera_angle']} | {row['camera_movement']} "
            f"| {timing} | {_cell(cast, 20)} | {row['transition']} "
            f"| {_cell(row['narration'])} |"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "CAMERA_ANGLES",
    "CAMERA_MOVEMENTS",
    "EST_CHARS_PER_SEC",
    "SHOT_SIZES",
    "TRANSITIONS",
    "derive_camera_angle",
    "derive_camera_movement",
    "derive_shot_size",
    "enrich_draft",
    "estimate_beat_seconds",
    "normalize_camera_angle",
    "normalize_camera_movement",
    "normalize_shot_size",
    "normalize_transition",
    "segment_scenes",
    "storyboard_markdown",
    "storyboard_rows",
]
