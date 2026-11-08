"""Reference media numbering gate (``qa.reference_media_numbering_gate``).

Clean-room restatement of the reference-numbering discipline
recorded in the Infinite Creation delta2 review (see
``INFINITE_CREATION_ATTRIBUTION.md``): reference media handed
to a video job are numbered independently per media type,
counting from zero, and each entry must point at the asset it
reuses. Images are capped at nine references and audio and
video at three each. This gate judges numbering records only:
it generates nothing, calls no model, and never certifies that
a reused reference keeps a subject consistent on screen.
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

_REFERENCE_FIELDS = ("ref_images", "ref_audios", "ref_videos")
_PREFIXES = {
    "ref_images": "ref_image_",
    "ref_audios": "ref_audio_",
    "ref_videos": "ref_video_",
}
_LIMITS = {"ref_images": 9, "ref_audios": 3, "ref_videos": 3}
_ALLOWED_TOP_LEVEL = (*_REFERENCE_FIELDS, "plan_id")

_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.reference_media_numbering_gate: {detail}"}
    issue.update(extra)
    return issue


def check_reference_media_numbering(references: Any) -> dict[str, Any]:
    """Judge one reference media numbering record.

    ``references`` carries ``ref_images``, ``ref_audios`` and
    ``ref_videos`` (each a list of ``{"ref_id", "asset_id"}``)
    and an optional ``plan_id``. Verdict ``pass`` means every
    entry is numbered ``<prefix><position>`` from zero with no
    gaps, every entry names the asset it reuses, and no type
    exceeds its cap (images 9, audio 3, video 3).
    """
    if not isinstance(references, dict):
        raise CapabilityError("reference numbering record must be an object")
    issues: list[dict[str, Any]] = []
    issues.extend(
        _issue("unknown_field", f"unknown top-level field {key!r}")
        for key in references
        if key not in _ALLOWED_TOP_LEVEL
    )
    counts: dict[str, int] = {}
    for field in _REFERENCE_FIELDS:
        entries = references.get(field, [])
        if not isinstance(entries, list):
            raise CapabilityError(f"{field} must be a list when present")
        counts[field] = len(entries)
        if len(entries) > _LIMITS[field]:
            issues.append(
                _issue(
                    "limit_exceeded",
                    f"{field} has {len(entries)} entries, cap is {_LIMITS[field]}",
                    field=field,
                )
            )
        prefix = _PREFIXES[field]
        for position, entry in enumerate(entries):
            if not isinstance(entry, dict):
                issues.append(_issue("entry_not_object", f"{field}[{position}] is not an object"))
                continue
            expected = f"{prefix}{position}"
            ref_id = entry.get("ref_id")
            if ref_id != expected:
                issues.append(
                    _issue(
                        "numbering_mismatch",
                        f"{field}[{position}] ref_id {ref_id!r} must be {expected!r}",
                        field=field,
                    )
                )
            elif not _SLUG_RE.match(str(ref_id)):
                issues.append(
                    _issue(
                        "ref_id_invalid", f"{field}[{position}] ref_id must be a slug", field=field
                    )
                )
            if not isinstance(entry.get("asset_id"), str) or not entry["asset_id"].strip():
                issues.append(
                    _issue(
                        "asset_missing",
                        f"{field}[{position}] must name the asset it reuses via asset_id",
                        field=field,
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [
            "combined audio-plus-video cap reading is unconfirmed",
            "reuse effectiveness is unverified by this gate",
        ],
        "plan_id": references.get("plan_id"),
        "counts": counts,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_reference_media_numbering(params.get("references"))
    report_path = out_dir / "reference_media_numbering.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_reference_media_numbering_gate_capabilities_once() -> list[str]:
    """Register ``qa.reference_media_numbering_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_media_numbering_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "references": {"type": "object"},
                },
                "required": ["references"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Reference media numbering gate: references are numbered "
                "independently per media type from zero with no gaps, every "
                "entry names its reused asset, and images cap at 9 with "
                "audio and video capped at 3 each."
            ),
        )
    )
    return ["qa.reference_media_numbering_gate"]


__all__ = [
    "check_reference_media_numbering",
    "register_reference_media_numbering_gate_capabilities_once",
]
