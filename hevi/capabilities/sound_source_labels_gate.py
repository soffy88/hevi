"""Sound-source labelling gate (``qa.sound_source_labels_gate``).

Clean-room rewrite of the *method* in the rea-video field report
(``hevi-vs-rea-video.md`` section 2.1 item 2): a film's sound is
three tracks -- voice, music, sound effects -- and each track
must be labelled with its source and a confidence. Sound effects
are the weak track: the deterministic signal is barely better
than chance, so effects may only ever appear as low-confidence
candidates, never as settled findings. Music provenance that
leans one way must carry how it would be confirmed and stay
pending until confirmed. A track with no label is a gap, not a
pass.

Shape: ``{"tracks": {"voice": {"source", "confidence"},
"music": {"source", "confidence", "confirmation_method",
"status"}, "sfx": [{"candidate", "confidence"}]}}``. Confidence
is a number in [0, 1]. Effects candidates must have confidence
at most 0.5 and be marked ``candidate: true``. Music ``status``
is ``"pending"`` or ``"confirmed"``; a leaning source with no
confirmation method fails.
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

TRACKS = ("voice", "music", "sfx")
SFX_MAX_CONFIDENCE = 0.5


def _check_confidence(value: Any, where: str, issues: list[str]) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        issues.append(f"bad_confidence: {where} confidence {value!r} is not a number")
    elif not 0.0 <= float(value) <= 1.0:
        issues.append(f"bad_confidence: {where} confidence {value!r} outside [0, 1]")


def check_sound_sources(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether all three sound tracks carry source labels."""
    issues: list[str] = []
    if not isinstance(plan, dict):
        raise CapabilityError("sound-source plan must be an object")
    tracks = plan.get("tracks")
    if not isinstance(tracks, dict):
        issues.append("missing_tracks: plan declares no sound tracks")
        return {"verdict": "fail", "ok": False, "issues": issues}
    for track in TRACKS:
        entry = tracks.get(track)
        if entry is None:
            issues.append(f"unlabelled_track: {track}")
            continue
        if track == "sfx":
            if not isinstance(entry, list):
                issues.append("sfx_not_list: effects must be a candidate list")
                continue
            for candidate in entry:
                if not isinstance(candidate, dict):
                    issues.append("sfx_candidate_not_object")
                    continue
                _check_confidence(
                    candidate.get("confidence"),
                    f"sfx candidate {candidate.get('candidate')!r}",
                    issues,
                )
                conf = candidate.get("confidence")
                if isinstance(conf, (int, float)) and float(conf) > SFX_MAX_CONFIDENCE:
                    issues.append(
                        f"sfx_overconfident: candidate "
                        f"{candidate.get('candidate')!r} confidence {conf} "
                        "exceeds the low-confidence ceiling 0.5"
                    )
                if candidate.get("candidate") is not True:
                    issues.append(
                        "sfx_not_candidate: effects entries must be marked "
                        "candidate: true; settled effects findings are not allowed"
                    )
            continue
        if not isinstance(entry, dict):
            issues.append(f"track_not_object: {track}")
            continue
        if not entry.get("source"):
            issues.append(f"unlabelled_track: {track} has no source")
        _check_confidence(entry.get("confidence"), track, issues)
        if track == "music":
            if entry.get("status") not in ("pending", "confirmed"):
                issues.append(f"music_status_undeclared: {track}")
            elif entry.get("status") == "pending" and not entry.get("confirmation_method"):
                issues.append(
                    "music_unconfirmed: leaning music source without a "
                    "confirmation_method stays unusable"
                )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_sound_sources(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "sound_source_labels.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "ok": report["ok"],
        },
    )


_Registered = False


def register_sound_source_labels_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sound_source_labels_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Sound-source labelling gate (rea-video A4, "
                "clean-room): voice/music/effects labelled per track; "
                "effects only as low-confidence candidates; leaning "
                "music sources carry a confirmation method. See "
                "REA_VIDEO_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.sound_source_labels_gate"]


register_sound_source_labels_gate_capabilities_once()
