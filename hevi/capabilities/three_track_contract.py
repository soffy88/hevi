"""Three-track sound contract (``audio.three_track_contract``).

Clean-room rewrite of the *contract* behind the sound layer of
the rea-video field report (``hevi-vs-rea-video.md`` section
2.1 item 2): sound is handled as three tracks -- voice, music,
and effects -- and the contract states what each track's
separation record must contain before anyone claims the sound
was taken apart. Voice and music entries carry a source and a
confidence; effects entries are candidates only, capped at low
confidence, because the effects signal is barely better than
chance. Tempo and key measurements, when present, must name
their method; a bare number with no method fails.

This capability judges the contract only. It performs no
separation, downloads no model, and installs nothing: no
vocal-separation weights are fetched or used here. A plan that
claims separation without a separation record fails, and a
plan that claims effects findings above the low-confidence
ceiling fails.

Shape: ``{"tracks": {"voice": {"source", "confidence"},
"music": {"source", "confidence", "tempo": {"bpm", "method"},
"key": {"tonality", "method"}}, "sfx": [{"candidate",
"confidence"}]}, "separation": {"method", "record_ref"}}``.
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

SFX_MAX_CONFIDENCE = 0.5


def _check_confidence(value: Any, where: str, issues: list[str]) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        issues.append(f"bad_confidence: {where} {value!r} is not a number")
    elif not 0.0 <= float(value) <= 1.0:
        issues.append(f"bad_confidence: {where} {value!r} outside [0, 1]")


def check_three_track_contract(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether a three-track separation claim honours the contract."""
    issues: list[str] = []
    if not isinstance(plan, dict):
        raise CapabilityError("three-track contract plan must be an object")
    separation = plan.get("separation")
    if not isinstance(separation, dict) or not separation.get("method"):
        issues.append("separation_undeclared: no separation method recorded")
    elif not separation.get("record_ref"):
        issues.append("separation_without_record: method without a record_ref")
    tracks = plan.get("tracks")
    if not isinstance(tracks, dict):
        issues.append("missing_tracks: plan declares no sound tracks")
        return {"verdict": "fail", "ok": False, "issues": issues}
    for track in ("voice", "music"):
        entry = tracks.get(track)
        if not isinstance(entry, dict):
            issues.append(f"track_not_object: {track}")
            continue
        if not entry.get("source"):
            issues.append(f"track_without_source: {track}")
        _check_confidence(entry.get("confidence"), track, issues)
    music = tracks.get("music")
    if isinstance(music, dict):
        for measurement in ("tempo", "key"):
            entry = music.get(measurement)
            if entry is not None:
                if not isinstance(entry, dict) or not entry.get("method"):
                    issues.append(
                        f"measurement_without_method: music {measurement} "
                        "names no measurement method"
                    )
    sfx = tracks.get("sfx")
    if not isinstance(sfx, list):
        issues.append("sfx_not_list: effects must be a candidate list")
    else:
        for candidate in sfx:
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
                    "sfx_not_candidate: effects entries must be marked candidate: true"
                )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": not issues,
        "issues": issues,
        "separation_performed_here": False,
        "note": (
            "Contract only. No separation is performed by this "
            "capability and no separation weights are fetched."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_three_track_contract(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "three_track_contract.json"
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


def register_three_track_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="audio.three_track_contract",
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
                "Three-track sound contract (rea-video B4, "
                "clean-room): voice/music/effects separation claims "
                "judged against the contract; no separation is "
                "performed and no weights are fetched. See "
                "REA_VIDEO_ATTRIBUTION.md."
            ),
            line="audio",
        )
    )
    return ["audio.three_track_contract"]


register_three_track_contract_capabilities_once()
