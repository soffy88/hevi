"""Motion variant gate (``qa.motion_variant_gate``).

Clean-room declaration gate only, restated from the public
packaging of the Motion library (``motiondivision/motion``, MIT),
the open successor of Framer Motion. Motion ships two entry
points with different jobs: ``motion/react`` for React components
and hooks, and ``motion/dom`` for standalone DOM calls. A plan
must declare which entry point each use belongs to, and the
declared API kind must match that entry point: components and
hooks live under ``motion/react``; standalone calls live under
``motion/dom``. A bare ``motion`` or ``framer-motion`` import, or
a mismatched pairing, fails. No library code is copied or run
here; this gate judges declarations only. See
OPEN_SKILLS_ATTRIBUTION.md.
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

MOTION_VARIANTS: frozenset[str] = frozenset({"motion/react", "motion/dom"})

_API_KINDS: frozenset[str] = frozenset({"component", "hook", "standalone"})

# Which entry point each API kind belongs to. Hooks and components
# are React-side; standalone calls are DOM-side.
_KIND_VARIANT: dict[str, str] = {
    "component": "motion/react",
    "hook": "motion/react",
    "standalone": "motion/dom",
}


def motion_variants() -> frozenset[str]:
    """Return the closed Motion entry-point vocabulary."""
    return MOTION_VARIANTS


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_motion_variant(plan: Any) -> dict[str, Any]:
    """Validate a Motion usage plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Every use must declare
    its entry point and its API kind, and the two must agree.
    """
    issues: list[dict[str, Any]] = []
    uses_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "usage plan must be a JSON object")
            ],
            "usages": [],
            "variants": sorted(MOTION_VARIANTS),
        }
    usages = plan.get("usages")
    if not isinstance(usages, list) or not usages:
        issues.append(
            _issue(
                "usages_missing",
                "plan must declare a non-empty usages list",
            )
        )
        usages = usages if isinstance(usages, list) else []
    for index, use in enumerate(usages):
        label = f"usages[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(use, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each use must be an object")
            )
            uses_out.append(entry)
            continue
        import_source = use.get("import_source")
        entry["import_source"] = import_source
        if not isinstance(import_source, str) or import_source not in MOTION_VARIANTS:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:undeclared_variant",
                    f"{import_source!r} is not a declared Motion entry "
                    "point; declare 'motion/react' or 'motion/dom'",
                )
            )
        api_kind = use.get("api_kind")
        entry["api_kind"] = api_kind
        if not isinstance(api_kind, str) or api_kind not in _API_KINDS:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:unknown_api_kind",
                    "api_kind must be 'component', 'hook', or 'standalone'",
                )
            )
        elif (
            isinstance(import_source, str)
            and import_source in MOTION_VARIANTS
            and _KIND_VARIANT[api_kind] != import_source
        ):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:variant_api_mismatch",
                    f"a {api_kind} use belongs under "
                    f"{_KIND_VARIANT[api_kind]!r}, not {import_source!r}",
                )
            )
        if entry["issues"]:
            entry["ok"] = False
        uses_out.append(entry)
        issues.extend(entry["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "usages": uses_out,
        "variants": sorted(MOTION_VARIANTS),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_motion_variant(params.get("plan"))
    report_path = out_dir / "motion_variant.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_motion_variant_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.motion_variant_gate",
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
                "Motion variant gate: each use must declare "
                "'motion/react' or 'motion/dom', and its API kind "
                "(component/hook/standalone) must match that entry "
                "point; bare or mismatched imports fail."
            ),
        )
    )
    return ["qa.motion_variant_gate"]


__all__ = [
    "MOTION_VARIANTS",
    "motion_variants",
    "check_motion_variant",
    "register_motion_variant_gate_capabilities_once",
]
