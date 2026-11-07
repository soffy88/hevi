"""Camera baseline-drop-bridge gate (``qa.camera_baseline_drop_gate``).

Clean-room rewrite of the baseline-and-drop method in
``hevi-vs-oyasumi-gamedev.md`` item 3 (from the oyasumi-gamedev.com
manga-research series, restated in the report's own words): a
viewer first learns what is normal -- several panels in the same
camera family (same height tier, same distance tier) -- and only
then does one changed panel read as a highlight. The highlight
changes exactly one axis (height or distance, never both at once),
and the panel after it is a bridge: a reaction, a lingering beat,
or a new baseline. Height has three tiers (high / eye / low) and
distance has three tiers (wide / medium / close); the nine
combinations are a map of candidates, not a dictionary of
meanings.

This gate judges a shot sequence -- records supplied by the
caller -- not pictures. It checks:

1. Every shot declares a height tier, a distance tier, and a role
   (``baseline`` / ``drop`` / ``bridge``).
2. Before the first drop there are at least two consecutive
   baseline shots in the same camera family (same height and
   distance): the baseline must actually be established.
3. A drop changes exactly one axis against the previous shot.
   Changing both axes, or neither, fails.
4. The shot after a drop must be a bridge. A drop with no bridge
   fails.

Tier names are caller-declared strings from the closed
vocabularies below; no meaning is attached to any tier by this
module. This module judges plans only. It never generates, never
calls a model, never touches a budget.
"""

from __future__ import annotations

import json
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

HEIGHTS = ("high", "eye", "low")
DISTANCES = ("wide", "medium", "close")
ROLES = ("baseline", "drop", "bridge")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.camera_baseline_drop_gate: {detail}"}
    issue.update(extra)
    return issue


def check_camera_sequence(sequence: Any) -> dict[str, Any]:
    """Judge one shot sequence. Returns ``ok`` / ``verdict`` / ``issues``.

    ``sequence`` is an object with ``shots``: a list of objects
    with ``id``, ``height`` (``high`` / ``eye`` / ``low``),
    ``distance`` (``wide`` / ``medium`` / ``close``) and ``role``
    (``baseline`` / ``drop`` / ``bridge``).
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(sequence, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("sequence_not_object", "shot sequence must be an object")],
            "shot_count": 0,
        }
    shots = sequence.get("shots")
    if not isinstance(shots, list) or not shots:
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("shots_missing", "sequence must list at least one shot")],
            "shot_count": 0,
        }
    parsed: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        where = f"shot {index}"
        if not isinstance(shot, dict):
            issues.append(_issue("shot_not_object", f"{where} must be an object"))
            parsed.append({})
            continue
        shot_id = shot.get("id")
        if not isinstance(shot_id, str) or not shot_id.strip():
            issues.append(_issue("shot_id_missing", f"{where} must declare an id"))
        height = shot.get("height")
        distance = shot.get("distance")
        role = shot.get("role")
        if height not in HEIGHTS:
            issues.append(
                _issue(
                    "height_undeclared",
                    f"{where} ({shot_id!r}) must declare height "
                    f"high/eye/low, got {height!r}",
                    shot_id=shot_id,
                )
            )
        if distance not in DISTANCES:
            issues.append(
                _issue(
                    "distance_undeclared",
                    f"{where} ({shot_id!r}) must declare distance "
                    f"wide/medium/close, got {distance!r}",
                    shot_id=shot_id,
                )
            )
        if role not in ROLES:
            issues.append(
                _issue(
                    "role_undeclared",
                    f"{where} ({shot_id!r}) must declare role "
                    f"baseline/drop/bridge, got {role!r}",
                    shot_id=shot_id,
                )
            )
        parsed.append({"id": shot_id, "height": height, "distance": distance, "role": role})
    first_drop = next(
        (i for i, s in enumerate(parsed) if s.get("role") == "drop"), None
    )
    if first_drop is not None:
        baseline_run = 0
        for shot in parsed[:first_drop]:
            if (
                shot.get("role") == "baseline"
                and shot.get("height") == parsed[0].get("height")
                and shot.get("distance") == parsed[0].get("distance")
            ):
                baseline_run += 1
            else:
                baseline_run = 0
        if baseline_run < 2:
            issues.append(
                _issue(
                    "baseline_too_short",
                    "at least two consecutive baseline shots in the same "
                    "camera family must precede the first drop, so the "
                    "baseline is established before it is broken",
                )
            )
        for index, shot in enumerate(parsed):
            if shot.get("role") != "drop":
                continue
            previous = parsed[index - 1] if index > 0 else None
            if previous is None or previous.get("height") not in HEIGHTS or previous.get("distance") not in DISTANCES:
                issues.append(
                    _issue(
                        "drop_without_previous",
                        f"drop shot {shot.get('id')!r} has no usable previous "
                        "shot to measure its change against",
                        shot_id=shot.get("id"),
                    )
                )
            else:
                changed = sum(
                    [
                        shot.get("height") != previous.get("height"),
                        shot.get("distance") != previous.get("distance"),
                    ]
                )
                if changed == 0:
                    issues.append(
                        _issue(
                            "drop_no_change",
                            f"drop shot {shot.get('id')!r} changes neither "
                            "axis against the previous shot",
                            shot_id=shot.get("id"),
                        )
                    )
                elif changed == 2:
                    issues.append(
                        _issue(
                            "drop_changes_two_axes",
                            f"drop shot {shot.get('id')!r} changes both "
                            "height and distance; a drop changes exactly "
                            "one axis",
                            shot_id=shot.get("id"),
                        )
                    )
            following = parsed[index + 1] if index + 1 < len(parsed) else None
            if following is None or following.get("role") != "bridge":
                issues.append(
                    _issue(
                        "drop_without_bridge",
                        f"drop shot {shot.get('id')!r} must be followed by "
                        "a bridge shot (reaction, lingering beat, or new "
                        "baseline)",
                        shot_id=shot.get("id"),
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "issues": issues,
        "shot_count": len(shots),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_camera_sequence(params.get("sequence"))
    report_path = out_dir / "camera_baseline_drop_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_camera_baseline_drop_gate_capabilities_once() -> list[str]:
    """Register ``qa.camera_baseline_drop_gate`` on the registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.camera_baseline_drop_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {"sequence": {"type": "object"}},
                "required": ["sequence"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Camera baseline-drop-bridge gate: at least two same-family "
                "baseline shots precede the first drop, a drop changes "
                "exactly one axis, and a bridge shot follows every drop. "
                "Every shot declares height tier, distance tier and role. "
                "Judges plans only."
            ),
            line="qa",
        )
    )
    return ["qa.camera_baseline_drop_gate"]


register_camera_baseline_drop_gate_capabilities_once()
