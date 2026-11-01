"""Chroma-key gate (``qa.chroma_key_gate``).

Method reconstructed from the *article description* in
``hevi-vs-code-stage-mv.md`` section 3 (see
CODE_STAGE_MV_ATTRIBUTION.md): the "paper-cut" failure -- a
keyed figure pasted onto a stage -- is judged by six gates over
offline frame sequences and measured values. This module judges
evidence only. It performs no keying itself, reads no video and
calls no provider; the FFmpeg chromakey route is a contract
(key parameters plus a command builder, :func:`validate_key_params`
and :func:`build_ffmpeg_chromakey_command`), whose real run is
recorded separately as a sample, never claimed from this gate.

Six gates, each over per-frame measurements supplied by the
caller (nothing is measured here, so nothing can be faked by
omission -- a missing measurement fails its gate):

1. edge: edge transition width and green-fringe ratio.
2. spill: green spill ratio over the subject.
3. grounding: foot y vs stage ground-plane y (same resolution).
4. shadow: shadow present, and shadow direction vs light
   direction.
5. proportion: subject height ratio vs the designed ratio.
6. lighting: subject light direction / brightness vs the stage
   rig.

Thresholds are hevi-chosen defaults, recorded in the report
with the evidence, except the grounding tolerance of 2 px,
which is the tolerance stated in the source report. No
self-reported number from the article is used as a threshold
(see CODE_STAGE_MV_ATTRIBUTION.md).

Failure contract: malformed evidence (not a JSON object, no
non-empty frame list, a frame that is not an object) or an
invalid threshold override raises :class:`CapabilityError`.
Well-formed evidence that fails a gate returns
``verdict: "fail"`` with per-gate results; missing per-frame
measurements fail their gate with a named issue.
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

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

DEFAULT_THRESHOLDS: dict[str, float] = {
    "edge_transition_min_px": 1.0,
    "edge_transition_max_px": 8.0,
    "green_fringe_ratio_max": 0.02,
    "spill_ratio_max": 0.02,
    "grounding_max_px": 2.0,
    "shadow_angle_max_deg": 15.0,
    "light_angle_max_deg": 15.0,
    "height_ratio_max_delta": 0.03,
    "brightness_ratio_min": 0.8,
    "brightness_ratio_max": 1.25,
}

GATE_NAMES = ("edge", "spill", "grounding", "shadow", "proportion", "lighting")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _resolve_thresholds(overrides: Any) -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if overrides is None:
        return thresholds
    if not isinstance(overrides, dict):
        raise CapabilityError("qa.chroma_key_gate: thresholds must be a JSON object")
    for key, value in overrides.items():
        if key not in DEFAULT_THRESHOLDS:
            raise CapabilityError(f"qa.chroma_key_gate: unknown threshold {key!r}; known: {sorted(DEFAULT_THRESHOLDS)}")
        if not _is_num(value) or float(value) < 0:
            raise CapabilityError(f"qa.chroma_key_gate: threshold {key!r} must be a non-negative number")
        thresholds[key] = float(value)
    return thresholds


def _measurement(frame: dict[str, Any], field: str, issues: list[dict[str, Any]], frame_no: Any) -> float | None:
    value = frame.get(field)
    if not _is_num(value):
        issues.append(
            _issue(
                "measurement_missing",
                f"frame {frame_no!r} is missing a numeric measurement {field!r}; "
                "a gate cannot pass on missing measurements",
                frame=frame_no,
                field=field,
            )
        )
        return None
    return float(value)


def check_chroma_key_evidence(evidence: Any, *, thresholds: Any = None) -> dict[str, Any]:
    """Judge measured chroma-key evidence against the six gates."""
    if not isinstance(evidence, dict):
        raise CapabilityError("qa.chroma_key_gate: evidence must be a JSON object")
    frames = evidence.get("frames")
    if not isinstance(frames, list) or not frames:
        raise CapabilityError("qa.chroma_key_gate: evidence requires a non-empty 'frames' list")
    for entry in frames:
        if not isinstance(entry, dict):
            raise CapabilityError("qa.chroma_key_gate: every frame entry must be a JSON object")
    resolved = _resolve_thresholds(thresholds if thresholds is not None else evidence.get("thresholds"))
    designed_ratio = evidence.get("designed_height_ratio")
    if not _is_num(designed_ratio) or not 0.0 < float(designed_ratio) <= 1.0:
        raise CapabilityError(
            "qa.chroma_key_gate: evidence requires 'designed_height_ratio' in (0, 1]"
        )
    designed_ratio = float(designed_ratio)
    stage_light_angle = evidence.get("stage_light_angle_deg")
    if not _is_num(stage_light_angle):
        raise CapabilityError("qa.chroma_key_gate: evidence requires a numeric 'stage_light_angle_deg'")
    stage_light_angle = float(stage_light_angle)
    stage_light_intensity = evidence.get("stage_light_intensity")
    if not _is_num(stage_light_intensity) or float(stage_light_intensity) <= 0:
        raise CapabilityError("qa.chroma_key_gate: evidence requires a positive numeric 'stage_light_intensity'")
    stage_light_intensity = float(stage_light_intensity)

    issues: list[dict[str, Any]] = []
    gates: dict[str, dict[str, Any]] = {name: {"ok": True, "frames_failed": [], "worst": None} for name in GATE_NAMES}

    def fail_gate(name: str, frame_no: Any, issue: dict[str, Any]) -> None:
        gates[name]["ok"] = False
        gates[name]["frames_failed"].append(frame_no)
        issues.append(issue)

    for entry in frames:
        frame_no = entry.get("frame")
        # 1. edge
        transition = _measurement(entry, "edge_transition_px", issues, frame_no)
        fringe = _measurement(entry, "green_fringe_ratio", issues, frame_no)
        if transition is None or fringe is None:
            if transition is None or fringe is None:
                gates["edge"]["ok"] = False
                gates["edge"]["frames_failed"].append(frame_no)
        else:
            gates["edge"]["worst"] = max(gates["edge"]["worst"] or 0.0, transition)
            if transition < resolved["edge_transition_min_px"] or transition > resolved["edge_transition_max_px"]:
                fail_gate(
                    "edge",
                    frame_no,
                    _issue(
                        "edge_transition",
                        f"frame {frame_no!r} edge transition {transition:g}px outside "
                        f"[{resolved['edge_transition_min_px']:g}, {resolved['edge_transition_max_px']:g}]px",
                        frame=frame_no,
                        edge_transition_px=transition,
                    ),
                )
            if fringe > resolved["green_fringe_ratio_max"]:
                fail_gate(
                    "edge",
                    frame_no,
                    _issue(
                        "green_fringe",
                        f"frame {frame_no!r} green fringe ratio {fringe:g} exceeds {resolved['green_fringe_ratio_max']:g}",
                        frame=frame_no,
                        green_fringe_ratio=fringe,
                    ),
                )
        # 2. spill
        spill = _measurement(entry, "spill_ratio", issues, frame_no)
        if spill is None:
            gates["spill"]["ok"] = False
            gates["spill"]["frames_failed"].append(frame_no)
        else:
            gates["spill"]["worst"] = max(gates["spill"]["worst"] or 0.0, spill)
            if spill > resolved["spill_ratio_max"]:
                fail_gate(
                    "spill",
                    frame_no,
                    _issue(
                        "spill",
                        f"frame {frame_no!r} spill ratio {spill:g} exceeds {resolved['spill_ratio_max']:g}",
                        frame=frame_no,
                        spill_ratio=spill,
                    ),
                )
        # 3. grounding
        foot_y = _measurement(entry, "foot_y_px", issues, frame_no)
        ground_y = _measurement(entry, "ground_y_px", issues, frame_no)
        if foot_y is None or ground_y is None:
            gates["grounding"]["ok"] = False
            gates["grounding"]["frames_failed"].append(frame_no)
        else:
            gap = abs(foot_y - ground_y)
            gates["grounding"]["worst"] = max(gates["grounding"]["worst"] or 0.0, gap)
            if gap > resolved["grounding_max_px"]:
                fail_gate(
                    "grounding",
                    frame_no,
                    _issue(
                        "grounding",
                        f"frame {frame_no!r} foot y {foot_y:g}px vs ground y {ground_y:g}px: "
                        f"gap {gap:g}px exceeds {resolved['grounding_max_px']:g}px",
                        frame=frame_no,
                        foot_y_px=foot_y,
                        ground_y_px=ground_y,
                        gap_px=gap,
                    ),
                )
        # 4. shadow
        shadow_present = entry.get("shadow_present")
        if shadow_present is not True:
            fail_gate(
                "shadow",
                frame_no,
                _issue(
                    "shadow_missing",
                    f"frame {frame_no!r} has no shadow; a lost shadow is a downgrade, not a pass",
                    frame=frame_no,
                    shadow_present=shadow_present,
                ),
            )
        else:
            shadow_angle = _measurement(entry, "shadow_angle_deg", issues, frame_no)
            light_angle = _measurement(entry, "light_angle_deg", issues, frame_no)
            if shadow_angle is None or light_angle is None:
                gates["shadow"]["ok"] = False
                gates["shadow"]["frames_failed"].append(frame_no)
            else:
                diff = abs(shadow_angle - light_angle)
                gates["shadow"]["worst"] = max(gates["shadow"]["worst"] or 0.0, diff)
                if diff > resolved["shadow_angle_max_deg"]:
                    fail_gate(
                        "shadow",
                        frame_no,
                        _issue(
                            "shadow_angle",
                            f"frame {frame_no!r} shadow angle {shadow_angle:g} deg vs light "
                            f"{light_angle:g} deg: difference {diff:g} deg exceeds "
                            f"{resolved['shadow_angle_max_deg']:g} deg",
                            frame=frame_no,
                            shadow_angle_deg=shadow_angle,
                            light_angle_deg=light_angle,
                            difference_deg=diff,
                        ),
                    )
        # 5. proportion
        height_ratio = _measurement(entry, "subject_height_ratio", issues, frame_no)
        if height_ratio is None:
            gates["proportion"]["ok"] = False
            gates["proportion"]["frames_failed"].append(frame_no)
        else:
            delta = abs(height_ratio - designed_ratio)
            gates["proportion"]["worst"] = max(gates["proportion"]["worst"] or 0.0, delta)
            if delta > resolved["height_ratio_max_delta"]:
                fail_gate(
                    "proportion",
                    frame_no,
                    _issue(
                        "proportion",
                        f"frame {frame_no!r} subject height ratio {height_ratio:g} vs designed "
                        f"{designed_ratio:g}: delta {delta:g} exceeds {resolved['height_ratio_max_delta']:g}",
                        frame=frame_no,
                        subject_height_ratio=height_ratio,
                        designed_height_ratio=designed_ratio,
                        delta=delta,
                    ),
                )
        # 6. lighting consistency
        subject_angle = _measurement(entry, "subject_light_angle_deg", issues, frame_no)
        subject_intensity = _measurement(entry, "subject_light_intensity", issues, frame_no)
        if subject_angle is None or subject_intensity is None:
            gates["lighting"]["ok"] = False
            gates["lighting"]["frames_failed"].append(frame_no)
        else:
            angle_diff = abs(subject_angle - stage_light_angle)
            brightness_ratio = subject_intensity / stage_light_intensity
            gates["lighting"]["worst"] = max(gates["lighting"]["worst"] or 0.0, angle_diff)
            if angle_diff > resolved["light_angle_max_deg"]:
                fail_gate(
                    "lighting",
                    frame_no,
                    _issue(
                        "lighting_angle",
                        f"frame {frame_no!r} subject light angle {subject_angle:g} deg vs stage "
                        f"{stage_light_angle:g} deg: difference {angle_diff:g} deg exceeds "
                        f"{resolved['light_angle_max_deg']:g} deg",
                        frame=frame_no,
                        subject_light_angle_deg=subject_angle,
                        stage_light_angle_deg=stage_light_angle,
                        difference_deg=angle_diff,
                    ),
                )
            if brightness_ratio < resolved["brightness_ratio_min"] or brightness_ratio > resolved["brightness_ratio_max"]:
                fail_gate(
                    "lighting",
                    frame_no,
                    _issue(
                        "lighting_brightness",
                        f"frame {frame_no!r} subject/stage brightness ratio {brightness_ratio:g} outside "
                        f"[{resolved['brightness_ratio_min']:g}, {resolved['brightness_ratio_max']:g}]",
                        frame=frame_no,
                        brightness_ratio=brightness_ratio,
                    ),
                )

    for gate in gates.values():
        gate["frames_failed"] = sorted(set(gate["frames_failed"]), key=lambda v: (str(type(v)), v))
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "issues": issues,
        "gates": gates,
        "frames_checked": len(frames),
        "designed_height_ratio": designed_ratio,
        "stage_light_angle_deg": stage_light_angle,
        "stage_light_intensity": stage_light_intensity,
        "thresholds": resolved,
    }


def validate_key_params(params: Any) -> dict[str, Any]:
    """Validate FFmpeg chromakey parameters (contract only; no keying is run)."""
    if not isinstance(params, dict):
        raise CapabilityError("qa.chroma_key_gate: key params must be a JSON object")
    problems: list[str] = []
    color_hex = params.get("key_color_hex")
    if not isinstance(color_hex, str) or not _HEX_RE.match(color_hex.strip()):
        problems.append("key_color_hex: must be a #RRGGBB colour")
        color_hex = None
    else:
        color_hex = color_hex.strip().lower()
        red = int(color_hex[1:3], 16)
        green = int(color_hex[3:5], 16)
        blue = int(color_hex[5:7], 16)
        if not (green > red and green > blue and green >= 100):
            problems.append(
                f"key_color_hex: {color_hex} is not green-dominant "
                f"(r={red}, g={green}, b={blue}); a chroma key must key on green"
            )
    similarity = params.get("similarity", 0.10)
    if not _is_num(similarity) or not 0.0 < float(similarity) <= 1.0:
        problems.append("similarity: must be in (0, 1]")
    blend = params.get("blend", 0.10)
    if not _is_num(blend) or not 0.0 <= float(blend) <= 1.0:
        problems.append("blend: must be in [0, 1]")
    feather = params.get("edge_feather_px")
    if feather is not None and (not _is_num(feather) or float(feather) < 0):
        problems.append("edge_feather_px: must be >= 0 when present")
    ok = not problems
    return {
        "ok": ok,
        "problems": problems,
        "key_color_hex": color_hex,
        "similarity": float(similarity) if _is_num(similarity) else similarity,
        "blend": float(blend) if _is_num(blend) else blend,
        "edge_feather_px": float(feather) if _is_num(feather) else feather,
        "filter": (
            f"chromakey=0x{color_hex[1:]}:{float(similarity):g}:{float(blend):g}"
            if ok and color_hex is not None
            else None
        ),
    }


def build_ffmpeg_chromakey_command(
    foreground: str,
    background: str,
    output: str,
    *,
    key_params: Any = None,
    despill: bool = False,
) -> list[str]:
    """Build (never run) the ffmpeg argv for keying + overlaying a sample.

    ``foreground`` / ``background`` / ``output`` are path strings
    carried verbatim; existence is not checked here -- this is the
    contract, and the real run is recorded separately as a sample.
    ``despill`` inserts the ffmpeg ``despill`` filter after the key;
    it is off by default because it must be tuned per sample.
    """
    if not isinstance(foreground, str) or not foreground.strip():
        raise CapabilityError("qa.chroma_key_gate: foreground path must be a non-empty string")
    if not isinstance(background, str) or not background.strip():
        raise CapabilityError("qa.chroma_key_gate: background path must be a non-empty string")
    if not isinstance(output, str) or not output.strip():
        raise CapabilityError("qa.chroma_key_gate: output path must be a non-empty string")
    checked = validate_key_params(key_params or {"key_color_hex": "#00ff00"})
    if not checked["ok"]:
        raise CapabilityError(
            "qa.chroma_key_gate: invalid key params: " + "; ".join(checked["problems"])
        )
    key_filter = str(checked["filter"])
    if despill:
        key_filter += ",despill"
    filter_complex = (
        f"[0:v]{key_filter},format=yuva420p[keyed];"
        "[1:v][keyed]overlay=0:0:shortest=1[v]"
    )
    return [
        "ffmpeg",
        "-y",
        "-i",
        foreground,
        "-i",
        background,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        output,
    ]


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    mode = str(params.get("mode", "evidence"))
    if mode == "key_params":
        report: dict[str, Any] = validate_key_params(params.get("key_params"))
        ok = bool(report["ok"])
    elif mode == "command":
        command = build_ffmpeg_chromakey_command(
            params.get("foreground", ""),
            params.get("background", ""),
            params.get("output", ""),
            key_params=params.get("key_params"),
            despill=bool(params.get("despill", False)),
        )
        report = {"command": command, "filter_complex": command[command.index("-filter_complex") + 1]}
        ok = True
    else:
        report = check_chroma_key_evidence(
            params.get("evidence"), thresholds=params.get("thresholds")
        )
        ok = report["verdict"] == "pass"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "chroma_key_gate_report.json"
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


def register_chroma_key_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.chroma_key_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string"},
                    "evidence": {"type": "object"},
                    "thresholds": {"type": "object"},
                    "key_params": {"type": "object"},
                    "foreground": {"type": "string"},
                    "background": {"type": "string"},
                    "output": {"type": "string"},
                    "despill": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Chroma-key gate (method reconstructed from an article "
                "description; see CODE_STAGE_MV_ATTRIBUTION.md): six gates "
                "-- edge, spill, grounding, shadow, proportion, lighting "
                "-- over offline frame sequences and supplied measurements. "
                "Missing measurements fail their gate. The FFmpeg "
                "chromakey route is contract only here (key-parameter "
                "validation plus a command builder); no keying is run by "
                "this capability."
            ),
            line="qa",
        )
    )
    return ["qa.chroma_key_gate"]


register_chroma_key_gate_capabilities_once()
