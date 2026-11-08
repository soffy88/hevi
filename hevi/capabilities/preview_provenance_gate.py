"""Preview provenance gate (``qa.preview_provenance_gate``).

Clean-room discipline gate only. Motion previews may come from
three provenances: a release-hosted video, a local poster image, or
a locally rendered clip. A poster image is a still: it must never
be presented as evidence of motion. A claim that preview and render
are frame-identical is recorded as unverified unless the caller
supplies verification. Release-hosted previews must name their
source reference. This gate judges provenance declarations only; it
plays no video and renders nothing. No text, code, or asset from any
outside repository is copied here. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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

PREVIEW_KINDS: tuple[str, ...] = (
    "release_mp4",
    "local_poster",
    "rendered_local",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_preview_provenance(record: Any) -> dict[str, Any]:
    """Validate a preview provenance record. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Posters are never motion
    evidence; frame-identical claims stay unverified without
    verification; release previews must name a source reference.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(record, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "record_not_object",
                    "preview provenance record must be a JSON object",
                )
            ],
            "preview_kinds": list(PREVIEW_KINDS),
        }
    kind = record.get("preview_kind")
    if kind not in PREVIEW_KINDS:
        issues.append(
            _issue(
                "preview_kind_unknown",
                f"preview_kind must be one of {list(PREVIEW_KINDS)}",
            )
        )
    if kind == "local_poster" and record.get("used_as_motion_evidence") is True:
        issues.append(
            _issue(
                "poster_not_motion_evidence",
                "a poster image is a still and must never be presented "
                "as evidence of motion",
            )
        )
    if record.get("frame_identical_claim") is True:
        if record.get("frame_identical_verified") is not True:
            issues.append(
                _issue(
                    "frame_identical_unverified",
                    "a frame-identical claim is recorded as unverified "
                    "until verification is supplied",
                )
            )
    if kind == "release_mp4":
        source_ref = record.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref:
            issues.append(
                _issue(
                    "release_source_ref_missing",
                    "a release-hosted preview must name its source reference",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "preview_kinds": list(PREVIEW_KINDS),
        "frame_identical_status": (
            "verified"
            if record.get("frame_identical_verified") is True
            else "unverified"
        ),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_preview_provenance(params.get("record"))
    report_path = out_dir / "preview_provenance.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_preview_provenance_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.preview_provenance_gate",
            kind="line",
            aspects=["16:9", "9:16"],
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
            layer="oskill",
            description=(
                "Preview provenance gate: posters are never motion "
                "evidence, frame-identical claims stay unverified "
                "without verification, and release previews must "
                "name a source reference."
            ),
        )
    )
    return ["qa.preview_provenance_gate"]


__all__ = [
    "PREVIEW_KINDS",
    "check_preview_provenance",
    "register_preview_provenance_gate_capabilities_once",
]
