"""Sound-effect sourcing gate (``qa.sfx_sourcing_gate``).

Clean-room discipline gate only, restating the sourcing discipline
in our own words: prefer public-domain material, keep attribution
entries for attribution-licensed material, use only key-free
standard-library selection scripts, and refuse material whose
source is unknown. A track whose licence is missing or unrecognized
fails closed: unknown provenance is never treated as cleared. No
audio file, script, or text from any outside repository is copied
or bundled here. See VIDEO_SHOTCRAFT_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

KNOWN_LICENSES: tuple[str, ...] = (
    "CC0",
    "CC BY",
    "CC BY-SA",
    "CC BY-NC",
    "CC BY-NC-SA",
    "CC BY-ND",
    "CC BY-NC-ND",
    "public_domain",
    "proprietary_cleared",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_sfx_sourcing(plan: Any) -> dict[str, Any]:
    """Validate a sound-effect sourcing plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Every track must name a
    source and a known licence; attribution-licensed tracks need an
    attribution entry; no track may require a key; unknown sources
    fail closed.
    """
    issues: list[dict[str, Any]] = []
    tracks_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "sourcing plan must be a JSON object")
            ],
            "tracks": [],
        }
    tracks = plan.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        issues.append(
            _issue(
                "tracks_missing", "plan must declare a non-empty tracks list"
            )
        )
        tracks = tracks if isinstance(tracks, list) else []
    needs_attribution_list = False
    for index, track in enumerate(tracks):
        label = f"tracks[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(track, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each track must be an object")
            )
            tracks_out.append(entry)
            continue
        if not isinstance(track.get("source"), str) or not track.get("source"):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:source_unknown",
                    "each track must name its source; unknown provenance "
                    "fails closed",
                )
            )
        licence = track.get("license")
        if licence not in KNOWN_LICENSES:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:license_unknown",
                    f"licence must be one of {list(KNOWN_LICENSES)}",
                )
            )
        elif str(licence).startswith("CC BY"):
            needs_attribution_list = True
            attribution = track.get("attribution_entry")
            if not isinstance(attribution, str) or not attribution:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:attribution_entry_missing",
                        "attribution-licensed material needs an "
                        "attribution entry",
                    )
                )
        if track.get("key_required") is True:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:key_required",
                    "selection must use key-free standard-library "
                    "scripts; a key requirement fails",
                )
            )
        if entry["issues"]:
            entry["ok"] = False
        tracks_out.append(entry)
        issues.extend(entry["issues"])
    if needs_attribution_list and not plan.get("attribution_list"):
        issues.append(
            _issue(
                "attribution_list_missing",
                "the plan must carry an attribution list when any "
                "track needs attribution",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "tracks": tracks_out,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_sfx_sourcing(params.get("plan"))
    report_path = out_dir / "sfx_sourcing.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sfx_sourcing_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sfx_sourcing_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Sound-effect sourcing gate: every track names a "
                "source and a known licence, attribution-licensed "
                "material carries attribution entries, no key is "
                "required, and unknown provenance fails closed."
            ),
        )
    )
    return ["qa.sfx_sourcing_gate"]


__all__ = [
    "KNOWN_LICENSES",
    "check_sfx_sourcing",
    "register_sfx_sourcing_gate_capabilities_once",
]
