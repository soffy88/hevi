"""Event-to-music/lighting wiring (``qa.event_trigger_wiring``).

Clean-room rewrite of the *method* described in
``hevi-vs-code-stage-mv.md`` section 4: dance events drive a
versioned mapping table that names, per event type, one music
action and one stage action. This module judges and builds
wiring *plans* over offline artefacts only. It generates no
music, plays nothing back, and calls no music service: the
music actions (``kick`` / ``transition`` / ``accent`` /
``pause``) are plan entries for a downstream music step, and
the stage actions are parameterised from the stage template
(see ``pipeline.project_style_sheet``'s stage block, whose
validation is reused here, not duplicated).

Mapping table (version ``"1"``, hevi-chosen; the source
article names the footstep / turn / hold mappings in prose
and gives no numbers, so no article number is used as a
tolerance or offset):

* ``footstep`` -> music ``kick`` + stage ``ground_light``
* ``turn`` -> music ``transition`` + stage ``camera_move``
* ``raise_arm`` -> music ``accent`` + stage ``light_pulse``
* ``hold`` -> music ``pause`` + stage ``light_hold``

Every trigger time is ``event_t + offset_ms`` with the
rule's offset (0 ms in version 1). Timing is checked, never
assumed: :func:`check_wiring` recomputes every expected
trigger time from the events and the rules and fails on any
missing, extra or out-of-tolerance trigger. The tolerance
itself is calibrated from measured runs by
:func:`calibrate_tolerance` -- it is not copied from the
article, which states no tolerance value.

Low-confidence events do not trigger: an event below
``confidence_floor`` is listed as ``suppressed`` and emits
no trigger, matching the rule that sub-threshold detections
stay candidates. An event type with no rule in the active
table fails the wiring with a named ``missing_mapping``
issue; a request with no events at all, or with a missing
or invalid stage template, fails as well. Malformed input
(not a JSON object, events not a list, a non-numeric event
time) raises :class:`CapabilityError`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.project_style_sheet import validate_stage_block
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

RULES_VERSION = "1"

# Versioned mapping table. Changing any entry means bumping
# RULES_VERSION; callers that pin a version get exactly the
# table they asked for, never a silently changed one.
MAPPING_RULES: dict[str, dict[str, Any]] = {
    "footstep": {"music_action": "kick", "stage_action": "ground_light", "offset_ms": 0},
    "turn": {"music_action": "transition", "stage_action": "camera_move", "offset_ms": 0},
    "raise_arm": {"music_action": "accent", "stage_action": "light_pulse", "offset_ms": 0},
    "hold": {"music_action": "pause", "stage_action": "light_hold", "offset_ms": 0},
}

# Hevi-chosen default tolerance for trigger timing, used
# until calibrate_tolerance replaces it with a measured one.
DEFAULT_TOLERANCE_MS = 100.0
DEFAULT_CONFIDENCE_FLOOR = 0.5


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def resolve_rules(rules: Any) -> dict[str, dict[str, Any]]:
    """Resolve the active mapping table (default or caller-supplied)."""
    if rules is None:
        return {name: dict(rule) for name, rule in MAPPING_RULES.items()}
    if not isinstance(rules, dict) or not rules:
        raise CapabilityError("qa.event_trigger_wiring: rules must be a non-empty JSON object")
    resolved: dict[str, dict[str, Any]] = {}
    for name, rule in rules.items():
        if not isinstance(rule, dict):
            raise CapabilityError(
                f"qa.event_trigger_wiring: rule for {name!r} must be a JSON object"
            )
        music_action = rule.get("music_action")
        stage_action = rule.get("stage_action")
        offset_ms = rule.get("offset_ms", 0)
        if not isinstance(music_action, str) or not music_action.strip():
            raise CapabilityError(
                f"qa.event_trigger_wiring: rule for {name!r} needs a non-empty 'music_action'"
            )
        if not isinstance(stage_action, str) or not stage_action.strip():
            raise CapabilityError(
                f"qa.event_trigger_wiring: rule for {name!r} needs a non-empty 'stage_action'"
            )
        if not _is_num(offset_ms) or float(offset_ms) < 0:
            raise CapabilityError(
                f"qa.event_trigger_wiring: rule for {name!r} 'offset_ms' must be >= 0"
            )
        resolved[name] = {
            "music_action": music_action.strip(),
            "stage_action": stage_action.strip(),
            "offset_ms": float(offset_ms),
        }
    return resolved


def _validate_events(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list) or not events:
        raise CapabilityError(
            "qa.event_trigger_wiring: 'events' must be a non-empty list; "
            "wiring with no event input fails"
        )
    checked: list[dict[str, Any]] = []
    for entry in events:
        if not isinstance(entry, dict):
            raise CapabilityError("qa.event_trigger_wiring: every event must be a JSON object")
        event_type = entry.get("type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise CapabilityError("qa.event_trigger_wiring: every event needs a non-empty 'type'")
        t = entry.get("t")
        if not _is_num(t) or float(t) < 0:
            raise CapabilityError(
                f"qa.event_trigger_wiring: event {event_type!r} needs a numeric t >= 0"
            )
        confidence = entry.get("confidence")
        if not _is_num(confidence) or not 0.0 <= float(confidence) <= 1.0:
            raise CapabilityError(
                f"qa.event_trigger_wiring: event {event_type!r} needs a confidence in [0, 1]; "
                "unscored events cannot be wired"
            )
        checked.append({
            "type": event_type.strip(),
            "t": float(t),
            "confidence": float(confidence),
            "source": entry.get("source", "unspecified"),
        })
    checked.sort(key=lambda e: (e["t"], e["type"]))
    return checked


def normalise_stage_template(template: Any) -> dict[str, Any]:
    """Accept a bare stage block or a sheet wrapper; return the block.

    Returns ``{"block": ..., "sheet_id": ..., "version": ...}``
    where the sheet fields are ``None`` when a bare block was
    supplied. A non-object template raises; a missing block
    is reported by the caller as a wiring failure, not raised
    here, so both shapes stay distinguishable.
    """
    if template is None:
        return {"block": None, "sheet_id": None, "version": None}
    if not isinstance(template, dict):
        raise CapabilityError("qa.event_trigger_wiring: stage template must be a JSON object")
    block = template.get("stage") if isinstance(template.get("stage"), dict) else None
    if block is None and "lighting_rig" in template:
        block = template
    return {
        "block": block,
        "sheet_id": template.get("sheet_id"),
        "version": template.get("version"),
    }


def _stage_params(stage_action: str, block: dict[str, Any]) -> dict[str, Any]:
    """Derive stage-action parameters from the validated stage block."""
    rig = block.get("lighting_rig") or {}
    lights = rig.get("lights") or []
    first_light = lights[0] if lights else {}
    camera_path = block.get("camera_path") or {}
    particles = block.get("particles") or {}
    materials = block.get("materials") or {}
    floor = materials.get("floor") or {}
    if stage_action == "ground_light":
        return {
            "color_hex": first_light.get("color_hex"),
            "intensity": first_light.get("intensity"),
            "angle_deg": first_light.get("angle_deg"),
            "floor_color_hex": floor.get("color_hex"),
            "floor_reflective": floor.get("reflective"),
        }
    if stage_action == "camera_move":
        return {
            "movement": camera_path.get("movement"),
            "start_shot": camera_path.get("start_shot"),
            "end_shot": camera_path.get("end_shot"),
        }
    if stage_action == "light_pulse":
        return {
            "color_hex": first_light.get("color_hex"),
            "intensity": first_light.get("intensity"),
            "particles_kind": particles.get("kind"),
            "particles_density": particles.get("density"),
        }
    if stage_action == "light_hold":
        return {
            "color_hex": first_light.get("color_hex"),
            "intensity": first_light.get("intensity"),
            "hold": True,
        }
    return {
        "color_hex": first_light.get("color_hex"),
        "intensity": first_light.get("intensity"),
    }


def wire_events(
    events: Any,
    *,
    rules: Any = None,
    stage_template: Any = None,
    tolerance_ms: float = DEFAULT_TOLERANCE_MS,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
    beat_times: Any = None,
) -> dict[str, Any]:
    """Wire events to music + stage triggers under the mapping table.

    Returns a plan with ``verdict``. Well-formed input that
    cannot be wired (unmapped event type, missing/invalid
    stage template, every event suppressed) returns
    ``verdict: "fail"`` with named issues; malformed input
    raises.
    """
    if not _is_num(tolerance_ms) or float(tolerance_ms) <= 0:
        raise CapabilityError("qa.event_trigger_wiring: tolerance_ms must be > 0")
    if not _is_num(confidence_floor) or not 0.0 < float(confidence_floor) <= 1.0:
        raise CapabilityError("qa.event_trigger_wiring: confidence_floor must be in (0, 1]")
    checked_events = _validate_events(events)
    active_rules = resolve_rules(rules)
    issues: list[dict[str, Any]] = []
    normalised = normalise_stage_template(stage_template)
    block = normalised["block"]
    stage_problems: list[str] = []
    if block is None:
        issues.append(
            _issue(
                "stage_template_missing",
                "wiring needs a stage template (a stage block or a sheet "
                "carrying one); stage actions have no parameters without it",
            )
        )
    else:
        stage_report = validate_stage_block(block)
        if not stage_report["ok"]:
            stage_problems = list(stage_report["problems"])
            issues.append(
                _issue(
                    "stage_template_invalid",
                    "stage template failed stage-block validation: "
                    + "; ".join(stage_problems),
                    problems=stage_problems,
                )
            )
    beats: list[float] | None = None
    if beat_times is not None:
        if not isinstance(beat_times, list) or any(not _is_num(b) for b in beat_times):
            raise CapabilityError("qa.event_trigger_wiring: beat_times must be a list of numbers")
        beats = sorted(float(b) for b in beat_times) if beat_times else None
    triggers: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for event in checked_events:
        rule = active_rules.get(event["type"])
        if rule is None:
            issues.append(
                _issue(
                    "missing_mapping",
                    f"event type {event['type']!r} has no rule in the active "
                    f"mapping table (version {RULES_VERSION}); unmapped "
                    "events cannot be wired",
                    event_type=event["type"],
                    event_t=event["t"],
                )
            )
            continue
        if event["confidence"] < float(confidence_floor):
            suppressed.append({
                "type": event["type"], "t": event["t"],
                "confidence": event["confidence"],
                "reason": "below confidence_floor; candidates do not trigger",
            })
            continue
        trigger_t = event["t"] + rule["offset_ms"] / 1000.0
        trigger: dict[str, Any] = {
            "event_type": event["type"],
            "event_t": event["t"],
            "trigger_t": round(trigger_t, 4),
            "music_action": rule["music_action"],
            "stage_action": rule["stage_action"],
            "offset_ms": rule["offset_ms"],
            "stage_params": _stage_params(rule["stage_action"], block) if block is not None else None,
            "source": event["source"],
        }
        if beats:
            nearest = min(beats, key=lambda b: abs(b - trigger_t))
            trigger["nearest_beat_t"] = nearest
            trigger["beat_delta_ms"] = round((trigger_t - nearest) * 1000.0, 3)
        triggers.append(trigger)
    if not triggers and not issues:
        issues.append(
            _issue(
                "no_triggers",
                "every event was suppressed below the confidence floor; "
                "a wiring plan with no triggers fails",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "rules_version": RULES_VERSION,
        "issues": issues,
        "triggers": triggers,
        "suppressed": suppressed,
        "events_wired": len(triggers),
        "events_supplied": len(checked_events),
        "tolerance_ms": float(tolerance_ms),
        "confidence_floor": float(confidence_floor),
        "stage_template": {
            "present": block is not None,
            "ok": block is not None and not stage_problems,
            "problems": stage_problems,
            "sheet_id": normalised["sheet_id"],
            "version": normalised["version"],
        },
        "music_generated": False,
        "note": (
            "Plan only: music actions are entries for a downstream "
            "music step; no music was generated or played back here."
        ),
    }


def check_wiring(
    triggers: Any,
    events: Any,
    *,
    rules: Any = None,
    tolerance_ms: float = DEFAULT_TOLERANCE_MS,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> dict[str, Any]:
    """Recompute expected triggers and compare them with supplied ones."""
    if not isinstance(triggers, list):
        raise CapabilityError("qa.event_trigger_wiring: triggers must be a list")
    checked_events = _validate_events(events)
    active_rules = resolve_rules(rules)
    expected: list[dict[str, Any]] = []
    for event in checked_events:
        rule = active_rules.get(event["type"])
        if rule is None or event["confidence"] < float(confidence_floor):
            continue
        expected.append({
            "event_type": event["type"],
            "event_t": event["t"],
            "trigger_t": round(event["t"] + rule["offset_ms"] / 1000.0, 4),
            "music_action": rule["music_action"],
            "stage_action": rule["stage_action"],
        })
    issues: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    used: set[int] = set()
    for want in expected:
        best: int | None = None
        best_err: float | None = None
        for idx, got in enumerate(triggers):
            if idx in used or not isinstance(got, dict):
                continue
            if got.get("event_type") != want["event_type"]:
                continue
            got_t = got.get("trigger_t")
            if not _is_num(got_t):
                continue
            err_ms = (float(got_t) - want["trigger_t"]) * 1000.0
            if best_err is None or abs(err_ms) < abs(best_err):
                best, best_err = idx, err_ms
        if best is None:
            issues.append(
                _issue(
                    "trigger_missing",
                    f"no trigger for {want['event_type']!r} at t={want['event_t']:g}s",
                    event_type=want["event_type"], event_t=want["event_t"],
                )
            )
            continue
        used.add(best)
        got = triggers[best]
        errors.append({
            "event_type": want["event_type"],
            "event_t": want["event_t"],
            "expected_trigger_t": want["trigger_t"],
            "actual_trigger_t": float(got["trigger_t"]),
            "error_ms": round(float(best_err), 3),
        })
        if abs(float(best_err)) > float(tolerance_ms):
            issues.append(
                _issue(
                    "trigger_out_of_tolerance",
                    f"{want['event_type']!r} trigger error {float(best_err):g}ms "
                    f"exceeds tolerance {float(tolerance_ms):g}ms",
                    event_type=want["event_type"],
                    error_ms=round(float(best_err), 3),
                )
            )
        if got.get("music_action") != want["music_action"] or got.get("stage_action") != want["stage_action"]:
            issues.append(
                _issue(
                    "trigger_action_mismatch",
                    f"{want['event_type']!r} trigger actions "
                    f"{got.get('music_action')!r}/{got.get('stage_action')!r} != "
                    f"expected {want['music_action']!r}/{want['stage_action']!r}",
                    event_type=want["event_type"],
                )
            )
    for idx, got in enumerate(triggers):
        if idx not in used:
            issues.append(
                _issue(
                    "trigger_unexpected",
                    f"trigger {idx} ({got.get('event_type')!r} at "
                    f"{got.get('trigger_t')!r}) matches no expected event",
                    trigger_index=idx,
                )
            )
    errors_ms = [abs(e["error_ms"]) for e in errors]
    return {
        "verdict": "fail" if issues else "pass",
        "issues": issues,
        "errors": errors,
        "triggers_expected": len(expected),
        "triggers_supplied": len(triggers),
        "max_abs_error_ms": max(errors_ms) if errors_ms else None,
        "tolerance_ms": float(tolerance_ms),
        "rules_version": RULES_VERSION,
    }


def calibrate_tolerance(
    measurements: Any,
    *,
    margin_factor: float = 1.5,
    minimum_ms: float = 50.0,
    round_to_ms: float = 10.0,
) -> dict[str, Any]:
    """Calibrate a trigger tolerance from measured timing errors.

    ``measurements`` is a list of numbers (or objects carrying
    ``error_ms``). The calibrated tolerance is the largest
    observed absolute error times ``margin_factor``, rounded
    up to ``round_to_ms``, and never below ``minimum_ms``.
    The margin, minimum and rounding are hevi-chosen; the
    errors themselves must come from real runs (for example
    the dual-template runs in the B3 evidence, where the same
    events are wired through two stage templates and the
    trigger times are compared).
    """
    if not isinstance(measurements, list) or not measurements:
        raise CapabilityError(
            "qa.event_trigger_wiring: calibrate needs a non-empty list of measurements"
        )
    errors: list[float] = []
    for item in measurements:
        if isinstance(item, dict):
            value = item.get("error_ms")
        else:
            value = item
        if not _is_num(value):
            raise CapabilityError(
                "qa.event_trigger_wiring: every measurement needs a numeric error_ms"
            )
        errors.append(abs(float(value)))
    if not _is_num(margin_factor) or float(margin_factor) < 1.0:
        raise CapabilityError("qa.event_trigger_wiring: margin_factor must be >= 1.0")
    if not _is_num(minimum_ms) or float(minimum_ms) <= 0:
        raise CapabilityError("qa.event_trigger_wiring: minimum_ms must be > 0")
    if not _is_num(round_to_ms) or float(round_to_ms) <= 0:
        raise CapabilityError("qa.event_trigger_wiring: round_to_ms must be > 0")
    max_error = max(errors)
    raw = max_error * float(margin_factor)
    tolerance = max(float(minimum_ms), math.ceil(raw / float(round_to_ms)) * float(round_to_ms))
    return {
        "tolerance_ms": float(tolerance),
        "max_abs_error_ms": round(max_error, 3),
        "mean_abs_error_ms": round(sum(errors) / len(errors), 3),
        "measurements": len(errors),
        "margin_factor": float(margin_factor),
        "minimum_ms": float(minimum_ms),
        "round_to_ms": float(round_to_ms),
        "calibrated_from": "measured trigger-time errors (dual-template runs)",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    mode = str(params.get("mode", "wire"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if mode == "calibrate":
        report: dict[str, Any] = calibrate_tolerance(
            params.get("measurements"),
            margin_factor=float(params.get("margin_factor", 1.5)),
            minimum_ms=float(params.get("minimum_ms", 50.0)),
            round_to_ms=float(params.get("round_to_ms", 10.0)),
        )
        ok = True
    elif mode == "check":
        report = check_wiring(
            params.get("triggers"), params.get("events"),
            rules=params.get("rules"),
            tolerance_ms=float(params.get("tolerance_ms", DEFAULT_TOLERANCE_MS)),
            confidence_floor=float(params.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR)),
        )
        ok = report["verdict"] == "pass"
    else:
        report = wire_events(
            params.get("events"),
            rules=params.get("rules"),
            stage_template=params.get("stage_template"),
            tolerance_ms=float(params.get("tolerance_ms", DEFAULT_TOLERANCE_MS)),
            confidence_floor=float(params.get("confidence_floor", DEFAULT_CONFIDENCE_FLOOR)),
            beat_times=params.get("beat_times"),
        )
        ok = report["verdict"] == "pass"
    report_path = out_dir / "event_trigger_wiring_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report.get("verdict", "pass" if ok else "fail"),
            "ok": ok,
        },
    )


def register_event_trigger_wiring_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.event_trigger_wiring",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "events": {"type": "array"},
                    "triggers": {"type": "array"},
                    "rules": {"type": "object"},
                    "stage_template": {"type": "object"},
                    "tolerance_ms": {"type": "number"},
                    "confidence_floor": {"type": "number"},
                    "beat_times": {"type": "array"},
                    "measurements": {"type": "array"},
                    "margin_factor": {"type": "number"},
                    "minimum_ms": {"type": "number"},
                    "round_to_ms": {"type": "number"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Event-to-music/lighting wiring (method reconstructed "
                "from an article description; see "
                "CODE_STAGE_MV_ATTRIBUTION.md): a versioned mapping "
                "table from dance events (footstep / turn / raise_arm "
                " / hold) to music actions and stage actions, with "
                "timing checked against a measured tolerance. Plan "
                "and offline artefacts only: no music is generated."
            ),
            line="qa",
        )
    )
    return ["qa.event_trigger_wiring"]


register_event_trigger_wiring_capabilities_once()
