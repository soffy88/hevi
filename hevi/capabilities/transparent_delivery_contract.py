"""Transparent delivery contract (``qa.transparent_delivery_contract``).

Clean-room rewrite of the *delivery vocabulary* described in
``hevi-vs-open-3d-skills.md`` section 2.4 (alpha-cutout): a
transparent delivery names three outputs -- stacked-alpha video,
VP9 alpha video, and a WebP frame sequence -- states plainly
that VP9 alpha is not supported in Safari, and declares the
three-background check. This module judges delivery *plans*
only; it performs no keying and no encoding, and it never judges
its own output: a delivered transparent asset must separately
pass ``qa.chroma_key_gate``. Judging and making are separate;
this gate must not self-approve.

No author-reported number is used here: no volume ratio and no
resolution is baked in as a default. Resolutions and sizes are
caller-supplied plan fields, checked for presence only.

Failure contract: a malformed plan (not a JSON object, missing
``delivery`` section) raises :class:`CapabilityError`. A
well-formed plan that misstates the Safari position, omits a
format, omits a background check, or claims this gate replaces
the chroma-key gate returns ``verdict: "fail"`` with named
issues; it never raises.
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

_WS_RE = re.compile(r"\s+")


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _norm_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WS_RE.sub(" ", value.strip()).lower()


def check_transparent_delivery_plan(plan: Any) -> dict[str, Any]:
    """Judge one transparent delivery plan against the contract."""
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.transparent_delivery_contract: plan must be a JSON object"
        )
    delivery = plan.get("delivery")
    if not isinstance(delivery, dict):
        raise CapabilityError(
            "qa.transparent_delivery_contract: plan requires a 'delivery' object"
        )
    issues: list[dict[str, Any]] = []

    formats = delivery.get("formats")
    if not isinstance(formats, list):
        issues.append(
            _issue(
                "formats_missing",
                "delivery must list 'formats' as a list containing "
                "stacked_alpha, vp9_alpha and webp_frames",
            )
        )
        formats = []
    for name in ("stacked_alpha", "vp9_alpha", "webp_frames"):
        if name not in formats:
            issues.append(
                _issue(
                    "format_missing",
                    f"delivery must declare format {name!r}; the "
                    "transparent delivery is three outputs, not one",
                    format=name,
                )
            )

    stacked = delivery.get("stacked_alpha")
    if not isinstance(stacked, dict) or stacked.get("frame_height_doubled") is not True:
        issues.append(
            _issue(
                "stacked_alpha_shape_missing",
                "delivery must declare the stacked-alpha shape: "
                "stacked_alpha.frame_height_doubled=true (the colour "
                "frame stacked with its alpha frame)",
            )
        )

    if delivery.get("vp9_safari_supported") is not False:
        issues.append(
            _issue(
                "safari_claim_wrong",
                "delivery must state vp9_safari_supported=false: VP9 "
                "alpha video is not supported in Safari, and claiming "
                "otherwise misleads the delivery",
                vp9_safari_supported=delivery.get("vp9_safari_supported"),
            )
        )
    safari_note = delivery.get("safari_note")
    if not isinstance(safari_note, str) or "safari" not in safari_note.lower():
        issues.append(
            _issue(
                "safari_note_missing",
                "delivery must carry a 'safari_note' that names Safari "
                "and states the VP9 alpha limitation plainly",
            )
        )

    backgrounds = delivery.get("background_checks")
    if not isinstance(backgrounds, list) or not backgrounds:
        issues.append(
            _issue(
                "background_checks_missing",
                "delivery must list 'background_checks' covering three "
                "backgrounds: near-black, a light page colour, and the "
                "loudest brand colour",
            )
        )
        backgrounds = []
    parts: list[str] = []
    for entry in backgrounds:
        if isinstance(entry, str):
            parts.append(_norm_text(entry))
        elif isinstance(entry, dict):
            parts.append(_norm_text(entry.get("background", entry.get("name", ""))))
    joined = " | ".join(parts)
    dark_ok = ("black" in joined or "dark" in joined or "near-black" in joined)
    light_ok = "light" in joined
    brand_ok = "brand" in joined
    for label, ok in (
        ("near-black background", dark_ok),
        ("light page background", light_ok),
        ("loud brand-colour background", brand_ok),
    ):
        if not ok:
            issues.append(
                _issue(
                    "background_check_missing",
                    f"background_checks must declare a {label} check; "
                    "all three backgrounds are required",
                    background=label,
                )
            )

    if delivery.get("chroma_key_gate_separate") is not True:
        issues.append(
            _issue(
                "chroma_gate_separation_missing",
                "delivery must declare chroma_key_gate_separate=true: "
                "the delivered asset is judged separately by "
                "qa.chroma_key_gate; this contract judges the delivery "
                "plan only and never approves the keyed asset itself",
            )
        )
    if delivery.get("self_approval") is True:
        issues.append(
            _issue(
                "self_approval_claim",
                "this gate must not claim to approve the keyed asset: "
                "judging and making are separate, and the asset must "
                "pass qa.chroma_key_gate separately",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "formats": list(formats),
        "issues": issues,
        "note": (
            "VP9 alpha is not supported in Safari. This gate judges "
            "the delivery plan only; the delivered asset must pass "
            "qa.chroma_key_gate separately."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_transparent_delivery_plan(params.get("plan"))
    report_path = out_dir / "transparent_delivery_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass"},
    )


def register_transparent_delivery_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.transparent_delivery_contract",
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
                "Transparent delivery contract (open-3d-skills "
                "alpha-cutout discipline, clean-room): a delivery plan "
                "must name stacked-alpha, VP9 alpha and WebP frames, "
                "state plainly that VP9 alpha is not supported in "
                "Safari, and declare near-black, light-page and "
                "loud-brand background checks. Judges plans only; the "
                "delivered asset must separately pass "
                "qa.chroma_key_gate. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.transparent_delivery_contract"]


register_transparent_delivery_contract_capabilities_once()
