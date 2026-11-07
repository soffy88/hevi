"""Three-layer clip rendering + one-action-per-segment gate (``qa.three_layer_clip``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 4 ("three layers, one action per segment"): a clip prompt is
written in three layers that never mix --

1. ``[公共约束]`` -- the things that do not change from shot to
   shot: style, characters, wardrobe, and the fixed bans. Identical
   on every clip of the episode.
2. ``[静图瞬间]`` -- the opening still: what the frame looks like
   the moment the clip starts. Written exactly once.
3. ``[分阶段动作]`` -- the staged action, one line per beat window:
   one main action, one camera move, then the landing. Segments
   follow the beats' own time windows; durations are never split
   evenly, and the article's 0-3 / 3-7 / 7-10 second split is only
   an example for a 10-second shot, never a rule -- a segment's
   window is whatever its beat declares.

The counting rule: each segment carries at most one main action
and at most one camera move. Action clauses are counted from an
explicit ``action_clauses`` list when the plan supplies one
(structured input wins); otherwise the action text is split on
clause separators (``；`` / ``;`` / ``。`` / newlines) and on the
sequencing words ``然后`` / ``接着`` / ``随后`` / ``再`` /
``同时`` / ``一边``. The text split is a documented heuristic --
it can over-count a long single action -- so a plan that needs
precision supplies ``action_clauses``. Camera moves are counted
from the beat's single ``camera_move`` field plus camera verbs
(``推`` / ``拉`` / ``摇`` / ``移`` / ``跟`` / ``环绕`` /
``升降`` / ``俯`` / ``仰`` + ``镜头``) appearing in the action
text; more than one camera assertion in a segment fails.

The three layers coexist with the six-section H3 prompt structure
(``pipeline.scene_reference.H3_SECTIONS``): the six sections are
the H3 route's prompt structure and are never redefined or merged
here. Three layers organise clip text; six sections organise H3
scene assembly. Different routes, different structures, both kept.

Frozen fixtures: ``THREE_LAYER_FIXTURE_VERSION`` versions this
module's own fixture set (used by its tests and by the
``three_layer_clip`` samples in ``qa.prompt_eval_harness``, whose
``SAMPLE_VERSION`` was bumped alongside). Fixtures are never edited
in place; a changed expectation bumps the version.

Time precision: every rendered timecode carries milliseconds
(``_fmt_time`` formats to three decimals), so an exemplar value
such as 13.268s or 1.083s survives rendering verbatim. Per-beat
physical cameras: a beat may carry a ``camera`` dict (``height`` /
``distance`` / ``optical_axis`` / ``path``). When any beat carries
one, every beat must, each must be complete, and the same
physical camera on every beat fails unless the clip declares
``static_camera`` exactly true -- a repeated single-shot camera
flattened across beats is the failure this rule exists to catch.
"""

from __future__ import annotations

import json
import re
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

THREE_LAYER_FIXTURE_VERSION = "2"

# Per-beat physical camera fields (H3 exemplar gapfill): a beat's
# own camera position -- height, distance, optical axis, path.
BEAT_CAMERA_FIELDS = ("height", "distance", "optical_axis", "path")

_EPS = 1e-9

_CLAUSE_SPLIT_RE = re.compile(r"[；;。\n]+|然后|接着|随后|同时|一边|再(?=[^\s]{1,12}(?:，|,|；|。|$))")

_CAMERA_VERBS = (
    "推镜头", "拉镜头", "摇镜头", "移镜头", "跟镜头",
    "环绕镜头", "升降镜头", "俯拍", "仰拍",
    "推镜", "拉镜", "摇镜", "移镜", "跟镜", "环绕", "升降",
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fmt_time(seconds: float) -> str:
    # Millisecond precision, always three decimals: 13.268 and 1.083
    # must survive rendering verbatim, never round to 13.3 / 1.1.
    return f"{float(seconds):.3f}"


def count_action_clauses(beat: dict[str, Any]) -> dict[str, Any]:
    """Count the main-action clauses of one beat.

    An explicit ``action_clauses`` list wins over text splitting.
    Otherwise the action text is split on clause separators and
    sequencing words (documented heuristic -- see module docstring).
    """
    explicit = beat.get("action_clauses")
    if explicit is not None:
        if not isinstance(explicit, list) \
                or not all(isinstance(c, str) and c.strip() for c in explicit):
            return {"count": 0, "clauses": [],
                    "source": "explicit",
                    "issue": "action_clauses must be a list of non-empty strings"}
        clauses = [c.strip() for c in explicit]
        return {"count": len(clauses), "clauses": clauses,
                "source": "explicit", "issue": None}
    action = beat.get("action")
    if not isinstance(action, str) or not action.strip():
        return {"count": 0, "clauses": [], "source": "text",
                "issue": "beat action must be a non-empty string"}
    parts = [p.strip(" ，,") for p in _CLAUSE_SPLIT_RE.split(action)]
    clauses = [p for p in parts if p]
    return {"count": len(clauses), "clauses": clauses,
            "source": "text", "issue": None}


def count_camera_moves(beat: dict[str, Any]) -> dict[str, Any]:
    """Count the camera-move assertions of one beat.

    The beat's ``camera_move`` field is one assertion when present.
    Camera verbs in the action text add one more per distinct verb
    found -- a segment that both declares a move and narrates
    another one is asserting two moves.
    """
    assertions: list[str] = []
    move = beat.get("camera_move")
    if move:
        assertions.append(f"camera_move={move}")
    action = beat.get("action")
    if isinstance(action, str):
        for verb in _CAMERA_VERBS:
            if verb in action:
                assertions.append(f"action_text:{verb}")
    return {"count": len(assertions), "assertions": assertions}


def _camera_key(camera: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(camera.get(field, "")).strip() for field in BEAT_CAMERA_FIELDS)


def _format_beat_camera(camera: dict[str, Any]) -> str:
    labels = {"height": "高度", "distance": "距离",
              "optical_axis": "光轴", "path": "路径"}
    return "；".join(f"{labels[field]}{camera[field]}" for field in BEAT_CAMERA_FIELDS)


def check_beat_cameras(beats: Any, static_camera: Any) -> dict[str, Any]:
    """Per-beat physical cameras: complete, covering every beat, not silently repeated.

    Clips that carry no per-beat ``camera`` at all are untouched
    (the legacy shot-level camera still governs them). Once any
    beat declares its own physical camera, every beat must declare
    one, each complete, and an identical camera on every beat
    fails unless the clip declares ``static_camera`` exactly true.
    """
    issues: list[dict[str, Any]] = []
    cameras: list[dict[str, Any] | None] = []
    if not isinstance(beats, list):
        return {"ok": True, "issues": issues, "cameras": cameras}
    for beat in beats:
        if isinstance(beat, dict) and beat.get("camera") is not None:
            cameras.append(beat.get("camera"))
        else:
            cameras.append(None)
    if all(camera is None for camera in cameras):
        return {"ok": True, "issues": issues, "cameras": cameras}
    declared_static = static_camera is True
    if static_camera is not None and not declared_static:
        issues.append({
            "code": "bad_static_camera_declaration",
            "detail": "qa.three_layer_clip: 'static_camera' must be "
                     "exactly true to declare a static camera; any "
                     "other value is not a declaration",
        })
    keys: list[tuple[str, ...]] = []
    for index, camera in enumerate(cameras):
        if camera is None:
            issues.append({
                "code": "missing_beat_camera",
                "detail": f"qa.three_layer_clip: beat {index} carries no "
                         "per-beat camera while other beats do; a beat "
                         "without its own physical camera silently "
                         "inherits one it never declared",
            })
            continue
        if not isinstance(camera, dict):
            issues.append({
                "code": "incomplete_beat_camera",
                "detail": f"qa.three_layer_clip: beat {index} camera must "
                         "be an object with height / distance / "
                         "optical_axis / path",
            })
            continue
        missing = [field for field in BEAT_CAMERA_FIELDS
                   if not isinstance(camera.get(field), (str, int, float))
                   or isinstance(camera.get(field), bool)
                   or not str(camera.get(field)).strip()]
        if missing:
            issues.append({
                "code": "incomplete_beat_camera",
                "detail": f"qa.three_layer_clip: beat {index} camera is "
                         f"missing or empty: {', '.join(missing)}; a "
                         "physical camera needs height, distance, "
                         "optical axis and path",
            })
            continue
        keys.append(_camera_key(camera))
    valid_cameras = [c for c in cameras if isinstance(c, dict)
                     and all(str(c.get(f, "")).strip() for f in BEAT_CAMERA_FIELDS)]
    if keys and len(keys) == len(valid_cameras) \
            and len(set(keys)) == 1 and not declared_static:
        issues.append({
            "code": "repeated_beat_camera",
            "detail": "qa.three_layer_clip: the same physical camera "
                     f"({_format_beat_camera(valid_cameras[0])}) repeats on "
                     "every beat; give each beat its own camera "
                     "position, or declare static_camera exactly true "
                     "when the camera genuinely does not move",
        })
    return {"ok": not issues, "issues": issues, "cameras": cameras}


def check_beat_tiling(beats: Any, duration_s: Any) -> dict[str, Any]:
    """Beats must tile the shot: sorted, contiguous, no gap/overlap."""
    issues: list[dict[str, Any]] = []
    if not isinstance(beats, list) or not beats:
        return {"ok": False, "issues": [{
            "code": "beats_missing",
            "detail": "qa.three_layer_clip: staged action needs a "
                     "non-empty beats list",
        }]}
    if not _is_number(duration_s) or float(duration_s) <= 0:
        return {"ok": False, "issues": [{
            "code": "bad_duration_s",
            "detail": "qa.three_layer_clip: duration_s must be a positive "
                     "number for the tiling check",
        }]}
    cursor = 0.0
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            issues.append({
                "code": "beat_not_object",
                "detail": f"qa.three_layer_clip: beat {index} must be an object",
            })
            continue
        start, end = beat.get("t_start_s"), beat.get("t_end_s")
        if not _is_number(start) or not _is_number(end):
            issues.append({
                "code": "beat_without_window",
                "detail": f"qa.three_layer_clip: beat {index} needs numeric "
                         "t_start_s and t_end_s",
            })
            continue
        if float(start) < cursor - _EPS:
            issues.append({
                "code": "beat_overlap",
                "detail": f"qa.three_layer_clip: beat {index} starts at "
                         f"{start}s before the previous segment ends at "
                         f"{cursor}s",
            })
        elif float(start) > cursor + _EPS:
            issues.append({
                "code": "beat_gap",
                "detail": f"qa.three_layer_clip: beat {index} starts at "
                         f"{start}s, leaving a gap after {cursor}s; "
                         "segments must tile without gaps",
            })
        if float(end) <= float(start):
            issues.append({
                "code": "beat_empty_window",
                "detail": f"qa.three_layer_clip: beat {index} ends at or "
                         "before it starts",
            })
        cursor = max(cursor, float(end))
    if abs(cursor - float(duration_s)) > _EPS:
        issues.append({
            "code": "tiling_mismatch",
            "detail": "qa.three_layer_clip: beats tile to "
                     f"{cursor}s but duration_s is {duration_s}s",
        })
    return {"ok": not issues, "issues": issues}


def render_three_layer_clip(
    clip: dict[str, Any],
    *,
    bans: str = "",
) -> str:
    """Render one clip's prompt text in the three layers.

    ``clip`` carries: ``style`` (common), ``characters`` (list of
    names, common), ``still_instant`` (the opening still, layer 2),
    ``beats`` (layer 3, each with ``t_start_s`` / ``t_end_s`` /
    ``action`` and optional ``camera_move`` / ``landing`` /
    ``sound``), ``duration_s`` and ``aspect``. The still instant
    appears exactly once; the common layer carries the bans line.
    """
    lines: list[str] = []
    lines.append(f"[公共约束]{clip.get('style', '')}")
    characters = clip.get("characters") or []
    if characters:
        lines.append(f"[人物]{'、'.join(str(c) for c in characters)}")
    if bans:
        lines.append(f"[禁令]{bans}")
    still = str(clip.get("still_instant", "") or "").strip()
    lines.append(f"[静图瞬间]{still}")
    if clip.get("static_camera") is True:
        lines.append("[机位声明]静态机位：全段同一物理机位（已显式声明）")
    lines.append("[分阶段动作]")
    for beat in clip.get("beats") or []:
        start = _fmt_time(float(beat["t_start_s"]))
        end = _fmt_time(float(beat["t_end_s"]))
        move = beat.get("camera_move") or "保持机位"
        landing = str(beat.get("landing", "") or "").strip()
        segment = (f"[{start}–{end}秒]{move}／{beat['action']}")
        camera = beat.get("camera")
        if isinstance(camera, dict):
            segment += f"／机位：{_format_beat_camera(camera)}"
        if landing:
            segment += f"／落位：{landing}"
        sound = str(beat.get("sound", "") or "").strip()
        if sound:
            segment += f"／声音：{sound}"
        lines.append(segment)
    lines.append(
        f"[时长]{_fmt_time(float(clip['duration_s']))}秒"
        f"（{clip.get('aspect', '')}）")
    return "\n".join(lines)


def check_three_layer_clip(clip: Any, *, bans: str = "") -> dict[str, Any]:
    """Judge one clip: three layers present, tiling clean, one action/move per segment."""
    issues: list[dict[str, Any]] = []
    if not isinstance(clip, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [{
                "code": "clip_not_object",
                "detail": "qa.three_layer_clip: clip must be an object",
            }],
            "rendered": None,
        }
    if not str(clip.get("style", "") or "").strip():
        issues.append({
            "code": "missing_common_style",
            "detail": "qa.three_layer_clip: layer 1 (common constraints) "
                     "needs a non-empty style",
        })
    if not str(clip.get("still_instant", "") or "").strip():
        issues.append({
            "code": "missing_still_instant",
            "detail": "qa.three_layer_clip: layer 2 (still instant) needs "
                     "the opening still; a clip without its first frame "
                     "described has no instant to hold",
        })
    beats = clip.get("beats")
    tiling = check_beat_tiling(beats, clip.get("duration_s"))
    issues.extend(tiling["issues"])
    camera_check = check_beat_cameras(beats, clip.get("static_camera"))
    issues.extend(camera_check["issues"])
    segment_reports: list[dict[str, Any]] = []
    if isinstance(beats, list):
        for index, beat in enumerate(beats):
            if not isinstance(beat, dict):
                continue
            actions = count_action_clauses(beat)
            cameras = count_camera_moves(beat)
            segment_reports.append({
                "beat_index": index,
                "action_clauses": actions,
                "camera_moves": cameras,
                "camera": camera_check["cameras"][index]
                if index < len(camera_check["cameras"]) else None,
            })
            if actions["issue"]:
                issues.append({
                    "code": "bad_action_clauses",
                    "detail": f"qa.three_layer_clip: beat {index}: "
                             f"{actions['issue']}",
                })
            elif actions["count"] == 0:
                issues.append({
                    "code": "empty_action",
                    "detail": f"qa.three_layer_clip: beat {index} has no "
                             "main action",
                })
            elif actions["count"] > 1:
                issues.append({
                    "code": "too_many_actions",
                    "detail": f"qa.three_layer_clip: beat {index} packs "
                             f"{actions['count']} main actions "
                             f"({actions['clauses']}); one segment, one "
                             "main action -- split the segment",
                })
            if cameras["count"] > 1:
                issues.append({
                    "code": "too_many_camera_moves",
                    "detail": f"qa.three_layer_clip: beat {index} asserts "
                             f"{cameras['count']} camera moves "
                             f"({cameras['assertions']}); one segment, one "
                             "camera move",
                })
    rendered = None
    if not issues:
        rendered = render_three_layer_clip(clip, bans=bans)
        if rendered.count("[静图瞬间]") != 1:
            issues.append({
                "code": "still_instant_not_once",
                "detail": "qa.three_layer_clip: the still instant must "
                         "appear exactly once in the rendered text",
            })
            rendered = None
    ok = not issues
    return {"ok": ok, "verdict": "pass" if ok else "fail",
            "issues": issues, "segments": segment_reports,
            "rendered": rendered}


def build_three_layer_fixtures() -> list[dict[str, Any]]:
    """Frozen fixtures for this module (versioned, never edited in place)."""
    base: dict[str, Any] = {
        "style": "水墨淡彩，线条克制",
        "characters": ["阿兰"],
        "still_instant": "阿兰站在月洞门边，手扶门框，望向庭院",
        "duration_s": 10.0,
        "aspect": "16:9",
        "beats": [
            {"t_start_s": 0.0, "t_end_s": 3.0, "action": "阿兰抬起手",
             "camera_move": "static", "landing": "手停在半空",
             "sound": "风声"},
            {"t_start_s": 3.0, "t_end_s": 7.0, "action": "阿兰指向庭院",
             "camera_move": "static", "landing": "保持本镜构图",
             "sound": "风声"},
            {"t_start_s": 7.0, "t_end_s": 10.0, "action": "阿兰放下手",
             "camera_move": "static", "landing": "回到门边站姿",
             "sound": "风声"},
        ],
    }
    good = json.loads(json.dumps(base, ensure_ascii=False))
    two_actions = json.loads(json.dumps(base, ensure_ascii=False))
    two_actions["beats"][1]["action"] = "阿兰指向庭院，然后转身走向门内"
    two_cameras = json.loads(json.dumps(base, ensure_ascii=False))
    two_cameras["beats"][0]["camera_move"] = "dolly_in"
    two_cameras["beats"][0]["action"] = "阿兰抬起手，推镜头跟随"
    no_still = json.loads(json.dumps(base, ensure_ascii=False))
    no_still["still_instant"] = ""
    beat_cameras = json.loads(json.dumps(base, ensure_ascii=False))
    for position, beat in enumerate(beat_cameras["beats"]):
        beat["camera"] = {
            "height": f"眼高+{position}档",
            "distance": f"{2 + position}米",
            "optical_axis": "水平" if position != 1 else "俯视15度",
            "path": f"弧线{position + 1}",
        }
    repeated_cameras = json.loads(json.dumps(base, ensure_ascii=False))
    for beat in repeated_cameras["beats"]:
        beat["camera"] = {
            "height": "眼高", "distance": "2米",
            "optical_axis": "水平", "path": "固定",
        }
    static_cameras = json.loads(json.dumps(repeated_cameras, ensure_ascii=False))
    static_cameras["static_camera"] = True
    incomplete_camera = json.loads(json.dumps(base, ensure_ascii=False))
    incomplete_camera["beats"][0]["camera"] = {
        "height": "眼高", "distance": "2米",
        "optical_axis": "水平",
    }
    return [
        {"name": "good_three_layer_clip", "expect": "pass", "clip": good},
        {"name": "two_actions_in_one_segment_fails", "expect": "fail",
         "clip": two_actions},
        {"name": "two_camera_moves_in_one_segment_fails", "expect": "fail",
         "clip": two_cameras},
        {"name": "missing_still_instant_fails", "expect": "fail",
         "clip": no_still},
        {"name": "distinct_beat_cameras_pass", "expect": "pass",
         "clip": beat_cameras},
        {"name": "repeated_beat_camera_fails", "expect": "fail",
         "clip": repeated_cameras},
        {"name": "static_beat_camera_declared_passes", "expect": "pass",
         "clip": static_cameras},
        {"name": "incomplete_beat_camera_fails", "expect": "fail",
         "clip": incomplete_camera},
    ]


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_three_layer_clip(
        params.get("clip"), bans=str(params.get("bans", "") or ""))
    report_path = out_dir / "three_layer_clip.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_three_layer_clip_capabilities_once() -> list[str]:
    """Register ``qa.three_layer_clip`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.three_layer_clip",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "clip": {"type": "object"},
                    "bans": {"type": "string"},
                },
                "required": ["clip"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Three-layer clip gate: clip text in three layers "
                "(common constraints / still instant / staged "
                "action), beats tiling the shot without gaps, at "
                "most one main action plus one camera move per "
                "segment, millisecond timecodes, and per-beat "
                "physical cameras (height / distance / optical "
                "axis / path) that must differ across beats unless "
                "a static camera is explicitly declared. Coexists "
                "with the six-section H3 prompt structure; neither "
                "redefines the other."
            ),
            line="qa",
        )
    )
    return ["qa.three_layer_clip"]


register_three_layer_clip_capabilities_once()
