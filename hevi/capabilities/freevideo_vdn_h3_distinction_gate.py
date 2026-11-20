"""VDN-H3 versus H3 distinction gate (``qa.freevideo_vdn_h3_distinction_gate``).

FreeVideo runs VDN-H3, an 8-step distilled (DMD) derivative
of MiniMax H3 — not the original H3. The name must say so.
In the reviewer's own words: a model identity that calls
itself the original H3, claims equivalence with the original
H3, or carries FastH3 conclusions across without re-testing
fails. The distilled revision is pinned: the short revision
must be ``751739ee``. Picture quality and character
consistency differ from the original H3 and must be
re-verified on the new path; nothing from the original-H3
route transfers by assertion.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here. This gate judges model identity records only; it never
loads weights or runs a render.
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

PINNED_REVISION_PREFIX = "751739ee"
REQUIRED_STEPS = 8
DISTILLED_KIND = "vdn-h3-distilled"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_freevideo_vdn_h3_identity(identity: Any) -> dict[str, Any]:
    """Validate a VDN-H3 model identity record.

    Verdicts are ``pass`` / ``fail`` only. An identity fails
    when a required field is missing, when the model kind is
    not the distilled kind, when the revision is not pinned
    to ``751739ee``, when the step count is not 8, when the
    model name does not carry ``VDN-H3`` or presents itself
    bare as ``MiniMax H3``, when equivalence with the
    original H3 is claimed, or when FastH3 conclusions are
    carried across without re-verification.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(identity, dict):
        return fail("identity_not_object", "model identity must be a JSON object")
    for field in ("model_name", "model_kind", "revision", "steps"):
        if field not in identity:
            return fail("identity_field_missing", f"model identity must carry {field!r}")
    if identity["model_kind"] != DISTILLED_KIND:
        return fail(
            "model_kind_not_distilled",
            f"model_kind must be {DISTILLED_KIND!r}, got {identity['model_kind']!r}",
        )
    revision = identity["revision"]
    if not isinstance(revision, str) or not revision.startswith(PINNED_REVISION_PREFIX):
        return fail(
            "revision_not_pinned",
            f"revision must be pinned to {PINNED_REVISION_PREFIX}, got {revision!r}",
        )
    if identity["steps"] != REQUIRED_STEPS:
        return fail(
            "steps_not_eight",
            f"VDN-H3 is an {REQUIRED_STEPS}-step distilled model, got steps {identity['steps']!r}",
        )
    name = identity["model_name"]
    if not isinstance(name, str) or not name:
        return fail("model_name_invalid", "model_name must be a non-empty string")
    if "VDN-H3" not in name.upper():
        return fail(
            "model_name_missing_vdn",
            "model_name must carry VDN-H3 so the distilled model is never "
            f"presented as the original H3, got {name!r}",
        )
    if identity.get("claims_equivalent_to_h3") is True:
        return fail(
            "equivalence_claim_refused",
            "VDN-H3 is a distilled derivative, not the original H3; "
            "equivalence must not be claimed",
        )
    if identity.get("fasth3_conclusions_applied") is True:
        return fail(
            "fasth3_conclusions_not_transferable",
            "FastH3 conclusions from the original-H3 route do not "
            "transfer to VDN-H3; re-verify on the new path",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_freevideo_vdn_h3_identity(params.get("identity"))
    report_path = out_dir / "freevideo_vdn_h3_distinction_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_vdn_h3_distinction_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_vdn_h3_distinction_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "identity": {"type": "object"},
                },
                "required": ["identity"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "FreeVideo VDN-H3 distinction gate: the model is an "
                "8-step distilled derivative, revision pinned to "
                "751739ee, never presented as the original H3, no "
                "equivalence claims, FastH3 conclusions do not transfer."
            ),
        )
    )
    return ["qa.freevideo_vdn_h3_distinction_gate"]


__all__ = [
    "DISTILLED_KIND",
    "PINNED_REVISION_PREFIX",
    "REQUIRED_STEPS",
    "check_freevideo_vdn_h3_identity",
    "register_freevideo_vdn_h3_distinction_gate_capabilities_once",
]
