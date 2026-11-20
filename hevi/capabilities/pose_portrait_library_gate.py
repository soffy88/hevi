"""Portrait reference library gate (``qa.pose_portrait_library_gate``).

Index-only discipline for portrait references from
anhao/ai-pose-gallery-zh: 1499 portraits (正脸 893 + 造型氛围
606, 51 hairstyle subdivisions, four hair lengths). The gate
judges portrait reference declarations only; it never
downloads, copies, or generates an image. Images always stay
outside the repo under ``HEVI_POSE_GALLERY_HOME``.

Rights tension, stated plainly and never resolved here: the
upstream README calls the portrait library CC0 1.0 in one
place, while the LICENSE scope note says all of ``img/``
belongs to the original author and is not for commercial use.
Until the two are reconciled upstream, every portrait use is
treated as non-commercial, and every declaration must
acknowledge the tension. Portraits are reference pictures,
never face-swap material, and never for real people or minors.
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

MODES: frozenset[str] = frozenset({"正脸", "造型氛围"})
HAIR_LENGTHS: frozenset[str] = frozenset({"短发", "中发", "中长发", "长发"})
TOTAL_PORTRAITS = 1499
FACE_COUNT = 893
MOOD_COUNT = 606


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_pose_portrait(portrait: Any) -> dict[str, Any]:
    """Validate one portrait reference declaration.

    Verdicts are ``pass`` / ``fail`` only. A declaration fails
    when the mode or hair length is outside the verified
    vocabulary, commercial use is claimed, the CC0 tension is
    not acknowledged, or the portrait is put to real-person or
    minor use. Hairstyle names are not closed here: 51
    subdivisions exist upstream but their names were never
    verified, so a hairstyle must only be a non-empty string.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(portrait, dict):
        return fail("portrait_not_object", "portrait reference must be a JSON object")
    portrait_id = portrait.get("portrait_id")
    if not isinstance(portrait_id, str) or not portrait_id.strip():
        return fail(
            "portrait_id_missing",
            "portrait reference must carry a non-empty portrait_id",
        )
    if portrait.get("mode") not in MODES:
        return fail(
            "unknown_mode",
            f"portrait mode must be one of {sorted(MODES)}, got {portrait.get('mode')!r}",
        )
    if portrait.get("hair_length") not in HAIR_LENGTHS:
        return fail(
            "unknown_hair_length",
            f"hair length must be one of {sorted(HAIR_LENGTHS)}, "
            f"got {portrait.get('hair_length')!r}",
        )
    hairstyle = portrait.get("hairstyle")
    if hairstyle is not None and (not isinstance(hairstyle, str) or not hairstyle.strip()):
        return fail(
            "hairstyle_invalid",
            "hairstyle must be a non-empty string when given",
        )
    if portrait.get("commercial_use") is True:
        return fail(
            "commercial_use_refused",
            "portrait images are non-commercial reference only; "
            "commercial use is refused while the CC0 tension is unresolved",
        )
    if portrait.get("cc0_tension_acknowledged") is not True:
        return fail(
            "cc0_tension_unacknowledged",
            "the portrait library is called CC0 1.0 in the README "
            "and non-commercial in the LICENSE scope note; the two "
            "are unresolved, so every use must acknowledge the "
            "tension and stay non-commercial",
        )
    if portrait.get("real_person_use") is True:
        return fail(
            "real_person_use_refused",
            "portrait references are reference pictures, never face-swap material for real people",
        )
    if portrait.get("minor_use") is True:
        return fail(
            "minor_use_refused",
            "portrait references must never be used for minors",
        )
    counts = portrait.get("counts")
    if counts is not None:
        if not isinstance(counts, dict):
            return fail("counts_invalid", "portrait counts must be an object")
        expected = {"total": TOTAL_PORTRAITS, "face": FACE_COUNT, "mood": MOOD_COUNT}
        for key, value in expected.items():
            if key in counts and counts[key] != value:
                return fail(
                    "counts_mismatch",
                    f"portrait library {key} is {value}, got {counts[key]!r}",
                )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "portrait_id": portrait_id,
        "mode": portrait.get("mode"),
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_portrait(params.get("portrait"))
    report_path = out_dir / "pose_portrait_library_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_portrait_library_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_portrait_library_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "portrait": {"type": "object"},
                },
                "required": ["portrait"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery portrait reference gate: 1499 portraits "
                "over two modes and four hair lengths, non-commercial "
                "reference only while the CC0 tension is unresolved, "
                "never for real people or minors."
            ),
        )
    )
    return ["qa.pose_portrait_library_gate"]


__all__ = [
    "FACE_COUNT",
    "HAIR_LENGTHS",
    "MODES",
    "MOOD_COUNT",
    "TOTAL_PORTRAITS",
    "check_pose_portrait",
    "register_pose_portrait_library_gate_capabilities_once",
]
