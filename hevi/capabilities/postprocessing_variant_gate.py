"""Postprocessing variant gate (``qa.postprocessing_variant_gate``).

Clean-room declaration gate only. Two different postprocessing
implementations share the word "postprocessing" and must never be
mixed up in a plan: the standalone ``postprocessing`` package
(pmndrs, Zlib) and the passes bundled with three.js itself under
``examples/jsm`` (vendored in hevi's scene3d template under
``vendor/three/postprocessing``). A plan must declare which
variant each pass belongs to, and the declared import path must
agree with that variant: pmndrs paths import the bare package;
three.js paths import through the three.js addons/jsm tree or the
vendored copy. A mixed or undeclared pairing fails. No library
code is copied or run here; this gate judges declarations only.
See OPEN_SKILLS_ATTRIBUTION.md.
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

POSTPROCESSING_VARIANTS: frozenset[str] = frozenset({"pmndrs", "three-jsm"})

_THREE_MARKERS: tuple[str, ...] = (
    "three/addons/postprocessing",
    "three/examples/jsm/postprocessing",
    "vendor/three/postprocessing",
)


def postprocessing_variants() -> frozenset[str]:
    """Return the closed postprocessing-variant vocabulary."""
    return POSTPROCESSING_VARIANTS


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_three_path(import_path: str) -> bool:
    return any(marker in import_path for marker in _THREE_MARKERS)


def check_postprocessing_variant(plan: Any) -> dict[str, Any]:
    """Validate a postprocessing pass plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Every pass must declare
    its variant and an import path that agrees with it.
    """
    issues: list[dict[str, Any]] = []
    passes_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "pass plan must be a JSON object")
            ],
            "passes": [],
            "variants": sorted(POSTPROCESSING_VARIANTS),
        }
    passes = plan.get("passes")
    if not isinstance(passes, list) or not passes:
        issues.append(
            _issue(
                "passes_missing",
                "plan must declare a non-empty passes list",
            )
        )
        passes = passes if isinstance(passes, list) else []
    for index, item in enumerate(passes):
        label = f"passes[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(item, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each pass must be an object")
            )
            passes_out.append(entry)
            continue
        variant = item.get("variant")
        entry["variant"] = variant
        if not isinstance(variant, str) or variant not in POSTPROCESSING_VARIANTS:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:undeclared_variant",
                    f"{variant!r} is not a declared postprocessing "
                    "variant; declare 'pmndrs' or 'three-jsm'",
                )
            )
        pass_name = item.get("pass_name")
        entry["pass_name"] = pass_name
        if not isinstance(pass_name, str) or not pass_name:
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:pass_name_missing", "each pass must be named")
            )
        import_path = item.get("import_path")
        entry["import_path"] = import_path
        if not isinstance(import_path, str) or not import_path:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:import_path_missing",
                    "each pass must declare its import path",
                )
            )
        elif variant == "pmndrs":
            if _is_three_path(import_path) or not (
                import_path == "postprocessing"
                or import_path.startswith("postprocessing/")
            ):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:pmndrs_path_mismatch",
                        "a pmndrs pass must import the bare "
                        "'postprocessing' package, not a three.js path",
                    )
                )
        elif variant == "three-jsm":
            if not _is_three_path(import_path):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:three_jsm_path_mismatch",
                        "a three-jsm pass must import through the "
                        "three.js addons/jsm tree or the vendored copy",
                    )
                )
        if entry["issues"]:
            entry["ok"] = False
        passes_out.append(entry)
        issues.extend(entry["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "passes": passes_out,
        "variants": sorted(POSTPROCESSING_VARIANTS),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_postprocessing_variant(params.get("plan"))
    report_path = out_dir / "postprocessing_variant.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_postprocessing_variant_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.postprocessing_variant_gate",
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
                "Postprocessing variant gate: each pass must declare "
                "'pmndrs' or 'three-jsm', and its import path must "
                "agree with that variant; mixed pairings fail."
            ),
        )
    )
    return ["qa.postprocessing_variant_gate"]


__all__ = [
    "POSTPROCESSING_VARIANTS",
    "postprocessing_variants",
    "check_postprocessing_variant",
    "register_postprocessing_variant_gate_capabilities_once",
]
