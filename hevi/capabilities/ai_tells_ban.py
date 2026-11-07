"""AI-tells ban (``qa.ai_tells_ban``).

Clean-room rewrite of the *method* of the AI-tells ban in
``win4r/video-director`` (MIT; see VIDEO_DIRECTOR_ATTRIBUTION.md):
a list of failure symptoms that mark generated footage as
machine-made, a fix for each symptom, and a symptom report that
translates what was seen into plain language. No text, code or
script from the source repository is copied here: the ban list
and the fixes below are written for hevi, in hevi's own words,
from the method idea alone (a banned symptom, its fix, and a
report field that says what was seen in plain language).

This module judges *records* -- a reviewer's observations over
frames that were actually looked at -- never a film directly.
An observation names a symptom from the ban list, the time it
was seen, and the frame/timestamp evidence for it. Any banned
symptom observed fails the record; the fix table says what to
do about it. A record with no observations over zero reviewed
frames is ``undetermined``, not a pass: nobody looked, so
nothing was cleared. An observation whose symptom is not in
the ban list is reported as unlisted (with a warning) and does
not fail the record on its own -- the ban list is the bar, and
an unlisted symptom is a candidate for extending it, not a
silent failure.

Each observation in the report carries two translation fields:
``reported_as`` (the symptom in plain language, for the
delivery report) and ``fix`` (the repair from the fix table).
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

# Ban list: symptom id -> plain-language description. A frame that
# shows any of these is machine-made-looking footage, however
# smooth the motion around it is.
BAN_LIST: dict[str, str] = {
    "morphing_hands": "hands or fingers change count, length or shape between frames",
    "melting_face": "a face warps, smears or loses its features mid-shot",
    "extra_limbs": "an extra arm, leg or hand appears that the body does not own",
    "gibberish_text": "on-screen text contains letter-like marks that spell nothing",
    "flickering_texture": "a surface strobes or crawls with unstable detail from frame to frame",
    "impossible_physics": "an object moves or rests in a way the real world forbids",
    "watermark_like_mark": "a faint logo-like or watermark-like mark the shot never asked for",
    "repeated_background_figures": "background figures repeat identically, as if stamped",
    "sliding_feet": "feet slide over the ground instead of planting and lifting",
    "detached_objects": "an object floats free of the hand or surface holding it",
}

# Failure -> repair. Every banned symptom has exactly one repair
# here; a symptom with no repair in the table is a gap in this
# module, and check_ai_tells says so instead of inventing one.
FIX_MAP: dict[str, str] = {
    "morphing_hands": "re-generate the shot with the hands out of frame or locked to a reference pose",
    "melting_face": "re-generate the shot from a locked face reference and cut before the warp",
    "extra_limbs": "re-generate the shot with the body fully framed against a clean background",
    "gibberish_text": "remove the text from the generation and add it as a clean overlay instead",
    "flickering_texture": "re-generate with the texture simplified, or freeze the surface as a still plate",
    "impossible_physics": "re-stage the action so the motion follows a real reference, then re-generate",
    "watermark_like_mark": "re-generate the shot and crop or cover the marked area only if the mark is gone",
    "repeated_background_figures": "re-generate with varied background figures, or replace the background plate",
    "sliding_feet": "re-generate with the walk cycle locked to ground contact, or cut to a static frame",
    "detached_objects": "re-generate with the object in contact with the hand or surface in every key frame",
}


def check_ai_tells(record: dict[str, Any]) -> dict[str, Any]:
    """Judge one symptom-observation record against the ban list.

    ``record`` carries ``observations`` (each with ``symptom``,
    ``evidence`` citing a frame/timestamp, and optionally
    ``t_sec``) and ``frames_reviewed`` (how many frames were
    actually looked at). Verdicts: ``"fail"`` when a banned
    symptom was observed, ``"pass"`` when frames were reviewed
    and no banned symptom was observed, ``"undetermined"``
    when no frames were reviewed at all.
    """
    if not isinstance(record, dict):
        raise CapabilityError("qa.ai_tells_ban: record must be an object (dict)")
    observations_raw = record.get("observations", [])
    if not isinstance(observations_raw, list):
        raise CapabilityError("qa.ai_tells_ban: observations must be a list")
    frames_reviewed = record.get("frames_reviewed", 0)
    if not isinstance(frames_reviewed, int) or isinstance(frames_reviewed, bool) \
            or frames_reviewed < 0:
        raise CapabilityError(
            f"qa.ai_tells_ban: frames_reviewed must be a non-negative integer, "
            f"got {frames_reviewed!r}")
    observations: list[dict[str, Any]] = []
    banned: list[dict[str, Any]] = []
    unlisted: list[dict[str, Any]] = []
    warnings: list[str] = []
    for idx, entry in enumerate(observations_raw):
        if not isinstance(entry, dict):
            raise CapabilityError(
                f"qa.ai_tells_ban: observation {idx} must be an object")
        symptom = entry.get("symptom")
        evidence = entry.get("evidence", "")
        if not isinstance(symptom, str) or not symptom.strip():
            raise CapabilityError(
                f"qa.ai_tells_ban: observation {idx} needs a symptom")
        if not isinstance(evidence, str) or not evidence.strip():
            raise CapabilityError(
                f"qa.ai_tells_ban: observation {idx} needs frame/timestamp evidence")
        symptom = symptom.strip()
        observed = {
            "symptom": symptom,
            "t_sec": entry.get("t_sec"),
            "evidence": evidence.strip(),
            "reported_as": BAN_LIST.get(symptom, f"unlisted symptom: {symptom}"),
            "fix": FIX_MAP.get(symptom),
        }
        observations.append(observed)
        if symptom in BAN_LIST:
            if symptom not in FIX_MAP:
                warnings.append(
                    f"banned symptom {symptom!r} has no repair in the fix table")
            banned.append(observed)
        else:
            unlisted.append(observed)
            warnings.append(
                f"observation {idx} symptom {symptom!r} is not in the ban list; "
                "reported as unlisted, not failed")
    if banned:
        verdict = "fail"
        reason = (f"{len(banned)} banned symptom(s) observed: "
                  f"{', '.join(sorted({o['symptom'] for o in banned}))}")
    elif frames_reviewed == 0:
        verdict = "undetermined"
        reason = ("no frames were reviewed: the ban was not checked, "
                  "and the record is not a pass")
    else:
        verdict = "pass"
        reason = (f"{frames_reviewed} frame(s) reviewed, "
                  "no banned symptom observed")
    return {
        "capability": "qa.ai_tells_ban",
        "verdict": verdict,
        "reason": reason,
        "frames_reviewed": frames_reviewed,
        "observations": observations,
        "banned_observations": banned,
        "banned_symptoms": sorted({o["symptom"] for o in banned}),
        "unlisted_observations": unlisted,
        "warnings": warnings,
        "ban_list": dict(BAN_LIST),
        "fix_map": dict(FIX_MAP),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_ai_tells(params.get("record", {}))
    report_path = out_dir / "ai_tells_ban_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "banned_symptoms": report["banned_symptoms"],
        },
    )


def register_ai_tells_ban_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.ai_tells_ban",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                },
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "AI-tells ban: judges a symptom-observation record "
                "against a ban list (morphing hands, melting faces, "
                "gibberish text, flicker, impossible physics and "
                "more), with a failure-to-repair table and a plain-"
                "language symptom report per observation. No frames "
                "reviewed means undetermined, never a pass. Judges "
                "records only; it watches no film itself."
            ),
            line="qa",
        )
    )
    return ["qa.ai_tells_ban"]


register_ai_tells_ban_capabilities_once()
