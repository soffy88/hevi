"""Multi-shot reference-lock planning (``video.multishot_lock``).

Clean-room implementation of a multi-shot, multi-reference production
method, written from the method description only: lock the look with a
first frame plus three-view references, separate each reference's job
in the prompt header, cut hard between shots, and keep a continuity
ledger.  No external code, character, image, or model is copied.

Honest provider boundary, stated in the output itself:

* hevi's ``video.fasth3_local`` takes exactly one reference image
  (``ref_image_1``) and a single-shot duration in the 5-15 s trained
  interval.  It does NOT take three images at once, and it does NOT
  generate a 2-3 s shot directly.
* Therefore, in this module, only the first frame is a real image
  input.  Person / animal / prop references become prompt-lock text
  (what the model may use them for, and what it must ignore), never
  extra image inputs.  A shot shorter than 5 s is never claimed as
  directly generatable: it is planned as "generate a longer segment,
  then hard-cut it with ``edit_assemble`` by timecode", and the trim
  timecodes for that are emitted explicitly.

Failure contract:

* Missing first frame, missing subject, or a three-view view that is
  absent / empty raises ``CapabilityError``.  Nothing is invented to
  fill the gap.
* A structurally invalid shot plan (duration sum mismatch, gap or
  overlap, duplicate shot id, two actions in one shot, a non-cut
  transition, missing camera fields) raises ``CapabilityError``.
* Continuity-ledger violations are REPORTED, never auto-rewritten
  into a pass: the package verdict becomes ``ledger_fail`` and the
  violations are listed.  Missing continuity evidence is reported
  as ``pending``, never as a pass.
* CPU only, zero paid calls, deterministic per plan.
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
_EPS = 1e-6

FASTH3_MIN_S = 5.0
FASTH3_MAX_S = 15.0

VIEWS = ("front", "side", "back")

RAIN_LEVELS = {"none": 0, "drizzle": 1, "light": 2, "moderate": 3, "heavy": 4}
WETNESS_LEVELS = {"dry": 0, "damp": 1, "wet": 2, "soaked": 3}
LIGHT_LEVELS = {"night": 0, "dusk": 1, "overcast": 2, "bright": 3}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityError(f"video.multishot_lock: {what} must be a JSON object")
    return value


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"video.multishot_lock: {what} must be a non-empty string")
    return value.strip()


def _level(value: Any, table: dict[str, int], what: str) -> int:
    if _is_num(value):
        return int(value)
    if isinstance(value, str) and value.strip() in table:
        return table[value.strip()]
    raise CapabilityError(f"video.multishot_lock: {what} must be one of {sorted(table)} or a number")


def _write_json(out_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# 1. Reference separation lock
# ---------------------------------------------------------------------------

def _normalise_subjects(references: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise subjects to a list, accepting a flat person/animal/prop form."""
    subjects = references.get("subjects")
    if subjects is None:
        subjects = []
        for kind in ("person", "animal", "prop"):
            raw = references.get(kind)
            if raw is not None:
                entry = dict(raw) if isinstance(raw, dict) else {}
                entry.setdefault("kind", kind)
                subjects.append(entry)
    if not isinstance(subjects, list) or not subjects:
        raise CapabilityError(
            "video.multishot_lock: references.subjects must be a non-empty list "
            "(or a person/animal/prop entry)"
        )
    normalised: list[dict[str, Any]] = []
    for idx, raw in enumerate(subjects):
        sub = _require_dict(raw, f"references.subjects[{idx}]")
        name = _require_str(sub.get("name"), f"references.subjects[{idx}].name")
        kind = _require_str(sub.get("kind"), f"references.subjects[{idx}].kind")
        if kind not in ("person", "animal", "prop"):
            raise CapabilityError(
                f"video.multishot_lock: subject {name!r} kind must be "
                "person, animal, or prop"
            )
        views = _require_dict(sub.get("views"), f"subject {name!r}.views")
        for view in VIEWS:
            _require_str(views.get(view), f"subject {name!r}.views.{view}")
        normalised.append({
            "name": name,
            "kind": kind,
            "views": {view: str(views[view]).strip() for view in VIEWS},
            "identity": sub.get("identity") if isinstance(sub.get("identity"), dict) else {},
        })
    names = [s["name"] for s in normalised]
    if len(set(names)) != len(names):
        raise CapabilityError("video.multishot_lock: duplicate subject name in references")
    return normalised


def validate_references(references: Any) -> dict[str, Any]:
    """Validate references; missing first frame / subject / view raises."""
    refs = _require_dict(references, "references")
    first_frame = _require_str(refs.get("first_frame"), "references.first_frame")
    subjects = _normalise_subjects(refs)
    return {"first_frame": first_frame, "subjects": subjects}


def build_reference_header(references: Any) -> str:
    """Role-separated prompt header. Each reference is given one job only."""
    refs = validate_references(references)
    lines = [
        "First frame is the opening frame of the first shot. "
        "Scene, wardrobe and lighting follow the first frame.",
    ]
    for sub in refs["subjects"]:
        name = sub["name"]
        if sub["kind"] == "person":
            lines.append(
                f"Subject {name} reference: use ONLY for face, facial "
                "proportions, face shape and hair colour. Do NOT use its "
                "grey background, wardrobe, or three-view layout."
            )
        elif sub["kind"] == "animal":
            lines.append(
                f"Subject {name} reference: use ONLY for breed, coat "
                "colour, markings, build and ear shape. Do NOT use its "
                "grey background or three-view layout."
            )
        else:
            lines.append(
                f"Subject {name} reference: use ONLY for its appearance "
                "as described in the continuity ledger. Do NOT use its "
                "background or layout."
            )
    lines.append(
        "Provider note: only the first frame is passed as an image "
        "input (fasth3_local ref_image_1). The other references above "
        "are prompt-lock text, not extra image inputs."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Multi-shot plan validation + short-shot trim plan
# ---------------------------------------------------------------------------

def validate_shot_plan(plan: Any) -> tuple[list[dict[str, Any]], float]:
    """Validate shots; returns (normalised shots, total duration)."""
    plan = _require_dict(plan, "plan")
    total = plan.get("total_duration_sec")
    if not _is_num(total) or float(total) <= 0:
        raise CapabilityError(
            "video.multishot_lock: plan.total_duration_sec must be a positive number"
        )
    total = float(total)
    shots_raw = plan.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise CapabilityError("video.multishot_lock: plan.shots must be a non-empty list")
    shots: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = 0.0
    for idx, raw in enumerate(shots_raw):
        shot = _require_dict(raw, f"plan.shots[{idx}]")
        sid = _require_str(shot.get("shot_id"), f"plan.shots[{idx}].shot_id")
        if sid in seen:
            raise CapabilityError(f"video.multishot_lock: duplicate shot_id {sid!r}")
        seen.add(sid)
        start = shot.get("start_sec")
        end = shot.get("end_sec")
        if not _is_num(start) or not _is_num(end):
            raise CapabilityError(f"video.multishot_lock: shot {sid!r} needs numeric start_sec/end_sec")
        start, end = float(start), float(end)
        if end <= start:
            raise CapabilityError(f"video.multishot_lock: shot {sid!r} needs end_sec > start_sec")
        if abs(start - cursor) > _EPS:
            raise CapabilityError(
                f"video.multishot_lock: shot {sid!r} starts at {start}s but the "
                f"previous shot ends at {cursor}s (gap or overlap; hard-cut plans "
                "must be contiguous)"
            )
        duration = end - start
        declared = shot.get("duration_sec")
        if declared is not None:
            if not _is_num(declared) or abs(float(declared) - duration) > _EPS:
                raise CapabilityError(
                    f"video.multishot_lock: shot {sid!r} duration_sec "
                    f"{declared!r} does not match end_sec - start_sec ({duration})"
                )
        action = shot.get("action")
        if not isinstance(action, str) or not action.strip():
            raise CapabilityError(f"video.multishot_lock: shot {sid!r} needs a non-empty action")
        actions = shot.get("actions")
        if actions is not None:
            if not isinstance(actions, list) or len(actions) != 1:
                raise CapabilityError(
                    f"video.multishot_lock: shot {sid!r} must do exactly one "
                    f"thing (actions must be a list of exactly one item)"
                )
        if shot.get("second_action") is not None:
            raise CapabilityError(
                f"video.multishot_lock: shot {sid!r} must do exactly one thing "
                "(second_action is not allowed)"
            )
        camera = _require_dict(shot.get("camera"), f"shot {sid!r}.camera")
        shot_size = _require_str(camera.get("shot_size"), f"shot {sid!r}.camera.shot_size")
        angle = _require_str(camera.get("angle"), f"shot {sid!r}.camera.angle")
        transition = shot.get("transition", "cut")
        if transition != "cut":
            raise CapabilityError(
                f"video.multishot_lock: shot {sid!r} transition must be 'cut' "
                f"(hard cut only), got {transition!r}"
            )
        shots.append({
            "shot_id": sid,
            "start_sec": start,
            "end_sec": end,
            "duration_sec": duration,
            "scene": shot.get("scene") if isinstance(shot.get("scene"), str) else "",
            "action": action.strip(),
            "camera": {
                "shot_size": shot_size,
                "angle": angle,
                "movement": camera.get("movement") if isinstance(camera.get("movement"), str) else "",
            },
            "transition": "cut",
            "characters": list(shot.get("characters", [])) if isinstance(shot.get("characters"), list) else [],
            "props": shot.get("props", []) if isinstance(shot.get("props"), list) else [],
            "movement_direction": shot.get("movement_direction"),
            "has_text": shot.get("has_text", False),
            "text_elements": shot.get("text_elements", []) if isinstance(shot.get("text_elements"), list) else [],
            "sound": shot.get("sound") if isinstance(shot.get("sound"), str) else "",
        })
        cursor = end
    if abs(cursor - total) > _EPS:
        raise CapabilityError(
            f"video.multishot_lock: shot durations sum to {cursor}s, not "
            f"plan.total_duration_sec ({total}s)"
        )
    return shots, total


def build_generation_segments(shots: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group shots into fasth3 generation segments and emit trim timecodes.

    Direct: one shot, 5-15 s, generated as-is.
    Short: consecutive shots grouped until the group reaches >= 5 s;
      a group still under 5 s is generated as a 5 s segment and the
      tail beyond the trims is discarded (reported, not hidden).
    Long: a shot over 15 s is split into equal chunks of <= 15 s.
    """
    segments: list[dict[str, Any]] = []
    trims: list[dict[str, Any]] = []

    def emit_segment(shot_ids: list[str], gen_duration: float, strategy: str,
                     trim_entries: list[dict[str, Any]]) -> None:
        seg_id = f"gen_{len(segments) + 1:02d}"
        trimmed_total = sum(t["duration_sec"] for t in trim_entries)
        segments.append({
            "segment_id": seg_id,
            "shot_ids": list(shot_ids),
            "generation_duration_sec": gen_duration,
            "strategy": strategy,
            "discard_tail_sec": round(max(0.0, gen_duration - trimmed_total), 6),
        })
        for entry in trim_entries:
            entry = dict(entry)
            entry["source_segment_id"] = seg_id
            trims.append(entry)

    def split_long_shot(shot: dict[str, Any]) -> None:
        duration = shot["duration_sec"]
        count = math.ceil(duration / FASTH3_MAX_S)
        chunk = duration / count
        for i in range(count):
            seg_id = f"gen_{len(segments) + 1:02d}"
            in_shot = i * chunk
            segments.append({
                "segment_id": seg_id,
                "shot_ids": [shot["shot_id"]],
                "generation_duration_sec": round(chunk, 6),
                "strategy": "split_long_shot",
                "discard_tail_sec": 0.0,
            })
            trims.append({
                "shot_id": shot["shot_id"],
                "source_segment_id": seg_id,
                "in_sec": 0.0,
                "out_sec": round(chunk, 6),
                "duration_sec": round(chunk, 6),
                "timeline_start_sec": round(shot["start_sec"] + in_shot, 6),
                "timeline_end_sec": round(shot["start_sec"] + in_shot + chunk, 6),
                "strategy": "split_long_shot",
            })

    pending: list[dict[str, Any]] = []
    pending_sum = 0.0

    def flush_pending() -> None:
        nonlocal pending, pending_sum
        if not pending:
            return
        gen_duration = pending_sum if pending_sum >= FASTH3_MIN_S else FASTH3_MIN_S
        entries: list[dict[str, Any]] = []
        offset = 0.0
        for shot in pending:
            entries.append({
                "shot_id": shot["shot_id"],
                "in_sec": round(offset, 6),
                "out_sec": round(offset + shot["duration_sec"], 6),
                "duration_sec": shot["duration_sec"],
                "timeline_start_sec": shot["start_sec"],
                "timeline_end_sec": shot["end_sec"],
                "strategy": "generate_long_then_trim",
            })
            offset += shot["duration_sec"]
        emit_segment([s["shot_id"] for s in pending], round(gen_duration, 6),
                     "generate_long_then_trim", entries)
        pending, pending_sum = [], 0.0

    for shot in shots:
        duration = shot["duration_sec"]
        if FASTH3_MIN_S <= duration <= FASTH3_MAX_S:
            flush_pending()
            emit_segment([shot["shot_id"]], duration, "direct", [{
                "shot_id": shot["shot_id"],
                "in_sec": 0.0,
                "out_sec": duration,
                "duration_sec": duration,
                "timeline_start_sec": shot["start_sec"],
                "timeline_end_sec": shot["end_sec"],
                "strategy": "direct",
            }])
        elif duration > FASTH3_MAX_S:
            flush_pending()
            split_long_shot(shot)
        else:  # short shot: accumulate
            if pending and pending_sum + duration > FASTH3_MAX_S:
                flush_pending()
            pending.append(shot)
            pending_sum += duration
            if pending_sum >= FASTH3_MIN_S:
                flush_pending()
    flush_pending()

    # Attach segment ids to shots for the caller.
    seg_by_shot: dict[str, str] = {}
    for seg in segments:
        for sid in seg["shot_ids"]:
            seg_by_shot.setdefault(sid, seg["segment_id"])
    return segments, trims


# ---------------------------------------------------------------------------
# 3. Continuity ledger (reported, never auto-rewritten)
# ---------------------------------------------------------------------------

def _prop_style(shot_props: Any) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    if not isinstance(shot_props, list):
        return out
    for item in shot_props:
        if isinstance(item, str):
            out[item] = None
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            out[item["name"]] = item.get("style") if isinstance(item.get("style"), str) else None
    return out


def check_continuity_ledger(plan: dict[str, Any], shots: list[dict[str, Any]],
                            references: dict[str, Any]) -> dict[str, Any]:
    """Return {verdict, violations, pending, checks}. No auto-fixing."""
    continuity = plan.get("continuity")
    if not isinstance(continuity, dict) or not continuity:
        return {
            "verdict": "pending",
            "violations": [],
            "pending": ["no continuity evidence supplied"],
            "checks": [{"name": "continuity_ledger", "status": "pending",
                        "detail": "no continuity block in plan"}],
        }
    violations: list[dict[str, Any]] = []
    pending: list[str] = []
    checks: list[dict[str, Any]] = []

    # Props: one ledger entry per prop, no duplicates, no conflicts.
    ledger_props = continuity.get("props")
    ledger_names: set[str] = set()
    if ledger_props is None:
        pending.append("props ledger missing")
        checks.append({"name": "props", "status": "pending", "detail": "no props ledger"})
    else:
        if not isinstance(ledger_props, list):
            raise CapabilityError("video.multishot_lock: continuity.props must be a list")
        for item in ledger_props:
            name = item if isinstance(item, str) else (item.get("name") if isinstance(item, dict) else None)
            if not isinstance(name, str) or not name.strip():
                raise CapabilityError("video.multishot_lock: every continuity prop needs a name")
            if name in ledger_names:
                violations.append({"code": "duplicate_prop", "prop": name,
                                   "message": f"prop {name!r} appears twice in the ledger"})
            ledger_names.add(name)
        if not any(v["code"] == "duplicate_prop" for v in violations):
            checks.append({"name": "props", "status": "pass",
                           "detail": f"{len(ledger_names)} unique prop(s) in ledger"})
    seen_styles: dict[str, str | None] = {}
    for shot in shots:
        for name, style in _prop_style(shot["props"]).items():
            if ledger_names and name not in ledger_names:
                violations.append({"code": "unknown_prop", "shot_id": shot["shot_id"], "prop": name,
                                   "message": f"shot {shot['shot_id']} uses prop {name!r} not in the ledger"})
            if style is not None:
                if name in seen_styles and seen_styles[name] != style:
                    violations.append({"code": "prop_style_conflict", "shot_id": shot["shot_id"], "prop": name,
                                       "message": f"prop {name!r} style changes across shots"})
                seen_styles.setdefault(name, style)

    # Subjects: shots may only use referenced subjects.
    known_subjects = {s["name"] for s in references["subjects"]}
    for shot in shots:
        for name in shot["characters"]:
            if name not in known_subjects:
                violations.append({"code": "unknown_subject", "shot_id": shot["shot_id"], "subject": name,
                                   "message": f"shot {shot['shot_id']} uses subject {name!r} with no reference"})

    # Weather / wetness / light: gradual only, wetness never reverses.
    weather = continuity.get("weather")
    if weather is None:
        pending.append("weather evidence missing")
        checks.append({"name": "weather_gradient", "status": "pending", "detail": "no weather entries"})
    else:
        if not isinstance(weather, list):
            raise CapabilityError("video.multishot_lock: continuity.weather must be a list")
        by_shot = {e.get("shot_id"): e for e in weather if isinstance(e, dict)}
        ordered = [s for s in shots if s["shot_id"] in by_shot]
        if len(ordered) < 2:
            pending.append("weather evidence covers fewer than 2 shots")
            checks.append({"name": "weather_gradient", "status": "pending",
                           "detail": "weather evidence covers fewer than 2 shots"})
        else:
            prev = None
            for shot in ordered:
                entry = by_shot[shot["shot_id"]]
                rain = _level(entry["rain"], RAIN_LEVELS, "weather.rain") if "rain" in entry else None
                wet = _level(entry["wetness"], WETNESS_LEVELS, "weather.wetness") if "wetness" in entry else None
                light = _level(entry["light"], LIGHT_LEVELS, "weather.light") if "light" in entry else None
                if prev is not None:
                    if rain is not None and prev[0] is not None and abs(rain - prev[0]) > 1:
                        violations.append({"code": "sudden_rain_change", "shot_id": shot["shot_id"],
                                           "message": f"rain jumps from {prev[0]} to {rain} in one cut"})
                    if wet is not None and prev[1] is not None:
                        if wet < prev[1]:
                            violations.append({"code": "wetness_reversed", "shot_id": shot["shot_id"],
                                               "message": f"wetness falls from {prev[1]} to {wet}"})
                        elif wet - prev[1] > 1:
                            violations.append({"code": "sudden_wetness_change", "shot_id": shot["shot_id"],
                                               "message": f"wetness jumps from {prev[1]} to {wet} in one cut"})
                    if light is not None and prev[2] is not None and abs(light - prev[2]) > 1:
                        violations.append({"code": "sudden_light_change", "shot_id": shot["shot_id"],
                                           "message": f"light jumps from {prev[2]} to {light} in one cut"})
                prev = (rain, wet, light)
            if not any(v["code"].startswith(("sudden_", "wetness_")) for v in violations):
                checks.append({"name": "weather_gradient", "status": "pass",
                               "detail": f"gradient checked over {len(ordered)} shot(s)"})

    # Movement direction: one declared direction, no reversal.
    direction = continuity.get("movement_direction")
    if direction is None:
        pending.append("movement_direction missing")
        checks.append({"name": "movement_direction", "status": "pending",
                       "detail": "no declared movement direction"})
    else:
        bad = [s["shot_id"] for s in shots
               if s.get("movement_direction") not in (None, "static", direction)]
        if bad:
            violations.append({"code": "direction_reversed", "shots": bad,
                               "message": f"movement direction reverses the declared {direction!r} in shots {bad}"})
        else:
            checks.append({"name": "movement_direction", "status": "pass",
                           "detail": f"all moving shots follow {direction!r}"})

    # No text, no brand, no subtitles.
    text_bad = [s["shot_id"] for s in shots if s.get("has_text") is True or s.get("text_elements")]
    if text_bad:
        violations.append({"code": "on_screen_text", "shots": text_bad,
                           "message": f"on-screen text in shots {text_bad}"})
    if continuity.get("brand_identifiers"):
        violations.append({"code": "brand_identifier",
                           "message": "brand identifiers declared in continuity"})
    if plan.get("has_subtitles") is True:
        violations.append({"code": "subtitles_present",
                           "message": "plan declares subtitles (this method requires none)"})
    if not text_bad and not continuity.get("brand_identifiers") and plan.get("has_subtitles") is not True:
        checks.append({"name": "no_text_no_brand", "status": "pass",
                       "detail": "no shot text, brand identifiers, or subtitles declared"})

    verdict = "fail" if violations else ("pending" if pending else "pass")
    return {"verdict": verdict, "violations": violations, "pending": pending, "checks": checks}


# ---------------------------------------------------------------------------
# 4. Package output (feeds prompt_compiler / edit_assemble)
# ---------------------------------------------------------------------------

def build_shot_prompt(header: str, shot: dict[str, Any],
                      references: dict[str, Any]) -> str:
    subjects = ", ".join(s["name"] for s in references["subjects"])
    lines = [
        "[参考]",
        header,
        f"[场景]{shot['scene']}" if shot["scene"] else "[场景]（未命名场景）",
        f"[镜头]{shot['shot_id']} {shot['start_sec']}–{shot['end_sec']}秒，"
        f"{shot['camera']['shot_size']}＋{shot['camera']['angle']}，硬切",
        f"[动作]{shot['action']}",
        f"[连贯]人物／动物：{subjects}；保持面容、服装、毛色、花纹、体型一致。",
    ]
    if shot["sound"]:
        lines.append(f"[声音]{shot['sound']}")
    lines.append("[约束]无字幕、无任何文字或品牌标识、无慢动作。")
    return "\n".join(lines)


def build_multishot_package(plan: Any) -> dict[str, Any]:
    """Build the full package; structural errors raise, ledger failures report."""
    plan = _require_dict(plan, "plan")
    references = validate_references(plan.get("references"))
    header = build_reference_header(plan.get("references"))
    shots, total = validate_shot_plan(plan)
    segments, trims = build_generation_segments(shots)
    ledger = check_continuity_ledger(plan, shots, references)

    seg_by_shot: dict[str, str] = {}
    for seg in segments:
        for sid in seg["shot_ids"]:
            seg_by_shot.setdefault(sid, seg["segment_id"])
    trim_by_shot: dict[str, list[dict[str, Any]]] = {}
    for trim in trims:
        trim_by_shot.setdefault(trim["shot_id"], []).append(trim)

    out_shots: list[dict[str, Any]] = []
    for shot in shots:
        out_shots.append({
            **shot,
            "prompt": build_shot_prompt(header, shot, references),
            "generation_segment_id": seg_by_shot.get(shot["shot_id"]),
            "trim_segments": trim_by_shot.get(shot["shot_id"], []),
        })

    if ledger["verdict"] == "pass":
        package_verdict = "ready"
    elif ledger["verdict"] == "fail":
        package_verdict = "ledger_fail"
    else:
        package_verdict = "pending"

    return {
        "package_verdict": package_verdict,
        "total_duration_sec": total,
        "shot_count": len(shots),
        "aspect": plan.get("aspect", "16:9"),
        "reference_header": header,
        "references": references,
        "shots": out_shots,
        "generation_segments": segments,
        "trim_segments": trims,
        "continuity_ledger": ledger,
        "fasth3_note": (
            "fasth3_local takes only ref_image_1 (the first frame) and "
            "5-15 s per generation. Person/animal references above are "
            "prompt-lock text, not extra image inputs. Shots under 5 s "
            "are planned as generate-long-then-trim, never as direct "
            "2-3 s generations."
        ),
        "prompt_compiler_input": {
            "style": plan.get("style", ""),
            "aspect": plan.get("aspect", "16:9"),
            "reference": header,
            "shots": [{
                "shot_id": s["shot_id"],
                "duration_s": s["duration_sec"],
                "scene": s["scene"],
                "action": s["action"],
                "camera": s["camera"],
            } for s in shots],
        },
        "edit_assemble_input": {
            "prompt_package": {
                "shots": [{
                    "shot_id": s["shot_id"],
                    "scene": s["scene"],
                    "action": s["action"],
                    "duration_sec": s["duration_sec"],
                    "transition": "cut",
                    "first_frame": references["first_frame"] if s["shot_id"] == shots[0]["shot_id"] else "",
                } for s in shots],
            },
            "trim_segments": trims,
            "clips_note": (
                "Clips are pending real generated files: after generation, "
                "fill one clip per generation segment (file, duration_sec), "
                "then map each trim's in_sec/out_sec onto its segment clip "
                "when building the edit_assemble EDL. No clip file is "
                "fabricated here."
            ),
        },
    }


def _render_multishot_lock(params: dict[str, Any], out_dir: Path, *,
                           duration: float, aspect: str, seed: int) -> CapabilityResult:
    package = build_multishot_package(params.get("plan"))
    report = _write_json(Path(out_dir), "multishot_lock.json", package)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "package_verdict": package["package_verdict"],
            "total_duration_sec": package["total_duration_sec"],
            "shot_count": package["shot_count"],
            "generation_segments": package["generation_segments"],
            "continuity_ledger": package["continuity_ledger"],
        },
    )


def register_multishot_lock_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="video.multishot_lock",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_multishot_lock,
        has_media_output=False,
        description=(
            "Multi-shot reference-lock planning: role-separated prompt "
            "header from first frame + three-view references, hard-cut "
            "shot-plan validation, short-shot generate-long-then-trim "
            "timecodes for fasth3_local, and a reported (never rewritten) "
            "continuity ledger. Emits prompts and trim timecodes for "
            "story.prompt_compiler and edit_assemble; generates no video."
        ),
        line="video",
    ))
    return ["video.multishot_lock"]


register_multishot_lock_capabilities_once()
