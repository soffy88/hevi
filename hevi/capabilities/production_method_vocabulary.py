"""Production-method label vocabulary gate (``qa.production_method_vocabulary``).

Clean-room rewrite of the *method* in the rea-video field report
(``hevi-vs-rea-video.md`` section 2.1 item 4): a finished film is
judged shot by shot, and every shot carries one production-method
label drawn from a closed vocabulary of ten classes. Overlay
layers (subtitles, captions, stickers, picture-in-picture) are
judged separately from the base picture and must never be folded
into the base label. A label is only a claim when it is bound to
evidence: a label pasted onto a shot with no evidence record is
rejected, because an unbound label is a guess wearing a
classification.

This gate judges records, not pixels. A caller who records
evidence that does not exist has lied to the gate; what the gate
does catch, mechanically, is the record-level disagreement --
an unknown label, a missing evidence binding, an overlay layer
hidden inside a base label -- before money is spent on a remake
plan built on a wrong label. It calls no model, holds no key,
and touches no budget. No accuracy figure from any upstream
evaluation is used as a threshold here.
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

BASE_LABELS = (
    "live_action",
    "ai_video",
    "digital_human",
    "3d_render",
    "2d_animation",
    "stop_motion",
    "code_template_render",
    "screen_capture",
    "still_push_pull",
    "still_frame",
)

OVERLAY_KINDS = (
    "subtitle",
    "caption_text",
    "sticker",
    "picture_in_picture",
)

_EVIDENCE_KINDS = (
    "aigc_marker",
    "frame_rate_fingerprint",
    "frozen_frame",
    "histogram_cut",
    "optical_flow",
    "noise_statistics",
    "metadata",
    "human_review",
)


def check_production_method_labels(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge a shot-by-shot production-method labelling plan.

    ``plan`` shape: ``{"shots": [{"id", "label", "evidence": {"kind",
    "ref"}}, ...], "overlays": [{"shot_id", "kind"}, ...]}``.
    Every shot needs a known label and an evidence record whose
    kind is in the closed evidence vocabulary. Overlay layers
    must be declared in ``overlays`` with a known kind; a base
    label naming an overlay kind fails.
    """
    issues: list[str] = []
    if not isinstance(plan, dict):
        raise CapabilityError("production-method plan must be an object")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append("missing_shots: plan declares no shots to label")
        return {"verdict": "fail", "ok": False, "issues": issues}
    seen: set[str] = set()
    for shot in shots:
        if not isinstance(shot, dict):
            issues.append("shot_not_object")
            continue
        shot_id = shot.get("id")
        if shot_id is None or shot_id in seen:
            issues.append(f"bad_shot_id: {shot_id!r}")
        seen.add(shot_id)
        label = shot.get("label")
        if label in OVERLAY_KINDS:
            issues.append(
                f"overlay_in_base_label: shot {shot_id!r} label {label!r} "
                "is an overlay kind and must be declared in overlays, not as a base label"
            )
        elif label not in BASE_LABELS:
            issues.append(f"unknown_label: shot {shot_id!r} label {label!r}")
        evidence = shot.get("evidence")
        if not isinstance(evidence, dict) or not evidence.get("kind"):
            issues.append(f"unbound_label: shot {shot_id!r} has no evidence record")
        elif evidence["kind"] not in _EVIDENCE_KINDS:
            issues.append(
                f"unknown_evidence_kind: shot {shot_id!r} evidence kind {evidence['kind']!r}"
            )
        elif not evidence.get("ref"):
            issues.append(f"unbound_label: shot {shot_id!r} evidence has no ref")
    overlays = plan.get("overlays", [])
    if not isinstance(overlays, list):
        issues.append("overlays_not_list")
        overlays = []
    shot_ids = {s.get("id") for s in shots if isinstance(s, dict)}
    for overlay in overlays:
        if not isinstance(overlay, dict):
            issues.append("overlay_not_object")
            continue
        if overlay.get("kind") not in OVERLAY_KINDS:
            issues.append(f"unknown_overlay_kind: {overlay.get('kind')!r}")
        if overlay.get("shot_id") not in shot_ids:
            issues.append(f"overlay_unknown_shot: {overlay.get('shot_id')!r}")
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_production_method_labels(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "production_method_labels.json"
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


def register_production_method_vocabulary_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.production_method_vocabulary",
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
                "Production-method label vocabulary gate (rea-video A1, "
                "clean-room): ten closed base labels plus separately "
                "declared overlay layers; every label must bind to an "
                "evidence record. See REA_VIDEO_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.production_method_vocabulary"]


register_production_method_vocabulary_capabilities_once()
