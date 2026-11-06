"""Dance reference-role gate (``qa.dance_reference_role_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): every reference
picture carries exactly one authority, and the authority
depends on the template. In the four-picture modern
template the first picture owns identity, the second owns
composition and camera language, the third owns the
walking route, and the fourth owns the environment. In
the three-picture classical template the second picture
is an overhead composition reference only. With a single
picture, the record must say plainly whether it locks
identity, environment, or both — and where the other half
comes from. This gate judges the role table only. It
draws nothing, renders nothing, and spends nothing:
``executed_here`` is always false.

This is the reference-role increment the Eian shotlist
gate does not cover: ``qa.shotlist_six_rule_gate`` judges
how shots are composed; this gate judges who each
reference picture is allowed to speak for.
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

ROLES: frozenset[str] = frozenset(
    {
        "identity",
        "composition_camera",
        "path_route",
        "environment",
        "overhead_composition",
        "identity_and_environment",
    }
)
TEMPLATES: frozenset[str] = frozenset({"four_modern", "three_classical", "single"})

# What each picture must be, per template. The second and
# third pictures never own identity or environment.
EXPECTED_ROLES: dict[str, dict[str, str]] = {
    "four_modern": {
        "picture_1": "identity",
        "picture_2": "composition_camera",
        "picture_3": "path_route",
        "picture_4": "environment",
    },
    "three_classical": {
        "picture_1": "identity",
        "picture_2": "overhead_composition",
        "picture_3": "environment",
    },
}

ENVIRONMENT_SOURCE: dict[str, str] = {
    "four_modern": "picture_4",
    "three_classical": "picture_3",
    "single": "picture_1",
}


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_dance_reference_roles(references: Any) -> dict[str, Any]:
    """Validate a reference-role table for one dance MV.

    Verdicts are ``pass`` / ``fail`` only. The table fails
    when its template is unknown, when a picture is missing
    or carries a role outside the closed vocabulary, when a
    picture claims two authorities or the wrong authority
    for its template, when a single picture locks identity
    without saying where the environment comes from (or the
    reverse), or when the stated conflict priority
    contradicts the template.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(references, dict):
        return fail("references_not_object", "reference roles must be a JSON object")
    template = references.get("template")
    if template not in TEMPLATES:
        return fail(
            "template_unknown",
            "reference template must be four_modern, three_classical or single",
        )
    roles = references.get("roles")
    if not isinstance(roles, dict) or not roles:
        return fail("roles_missing", "reference roles must name at least one picture")
    for picture, role in roles.items():
        if isinstance(role, list):
            return fail(
                "role_not_single",
                f"{picture} carries more than one authority; one picture holds exactly one role",
            )
        if role not in ROLES:
            return fail(
                "role_unknown",
                f"{picture} carries unknown role {role!r}; use the closed role vocabulary",
            )
    if template in EXPECTED_ROLES:
        expected = EXPECTED_ROLES[template]
        for picture, role in expected.items():
            if picture not in roles:
                return fail(
                    "role_missing",
                    f"{template} needs {picture} as {role}",
                )
            if roles[picture] != role:
                return fail(
                    "role_mismatch",
                    f"{picture} must be {role} in {template}, not {roles[picture]}",
                )
        for picture in roles:
            if picture not in expected:
                return fail(
                    "role_extra_picture",
                    f"{template} has no role for {picture}",
                )
    else:  # single-picture template
        if set(roles) != {"picture_1"}:
            return fail(
                "single_picture_only",
                "the single template locks exactly picture_1",
            )
        role = roles["picture_1"]
        if role == "identity":
            source = references.get("environment_source")
            if not isinstance(source, str) or not source.strip():
                return fail(
                    "environment_source_missing",
                    "picture_1 locks identity only; the record must "
                    "say where the environment comes from",
                )
        elif role == "environment":
            source = references.get("identity_source")
            if not isinstance(source, str) or not source.strip():
                return fail(
                    "identity_source_missing",
                    "picture_1 locks environment only; the record must "
                    "say where the identity comes from",
                )
        elif role not in {"identity_and_environment"}:
            return fail(
                "single_role_wrong",
                "a single picture locks identity, environment, or "
                "both together — never a camera or route role",
            )
    priority = references.get("priority")
    if not isinstance(priority, dict):
        return fail(
            "priority_missing",
            "reference roles must state the conflict priority",
        )
    if priority.get("identity_source") != "picture_1":
        return fail(
            "priority_identity_wrong",
            "identity is always decided by picture_1",
        )
    if priority.get("environment_source") != ENVIRONMENT_SOURCE[template]:
        return fail(
            "priority_environment_wrong",
            f"environment is decided by {ENVIRONMENT_SOURCE[template]} in {template}",
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
    report = check_dance_reference_roles(params.get("references"))
    report_path = out_dir / "dance_reference_role_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_reference_role_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_reference_role_gate",
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
            layer="oskill",
            description=(
                "Dance reference-role gate: four-picture modern, "
                "three-picture classical and single-picture templates "
                "with one authority per picture and stated priority."
            ),
        )
    )
    return ["qa.dance_reference_role_gate"]


__all__ = [
    "ENVIRONMENT_SOURCE",
    "EXPECTED_ROLES",
    "ROLES",
    "TEMPLATES",
    "check_dance_reference_roles",
    "register_dance_reference_role_gate_capabilities_once",
]
