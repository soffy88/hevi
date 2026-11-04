"""Workbench manifest gate (``qa.workbench_manifest_gate``).

Discipline gate only. A finished-film project that claims to open
in a browser workbench must carry a single manifest listing every
editable section, with the timeline taken from the same source as
the film's main composition. A second, hand-copied timeline is a
drift risk: edits made against a copy silently diverge from the
rendered film, so a hand-copied timeline fails. A project with no
manifest must say plainly that the workbench import entry point is
unavailable; claiming an import that cannot happen fails. The
manifest version is pinned: an unpinned or missing version fails.
This gate judges the plan only and builds no editor. See
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

# The closed section vocabulary of a workbench manifest, in the
# order the manifest declares them. No other section is admitted.
MANIFEST_SECTIONS: tuple[str, ...] = (
    "shots",
    "transitions",
    "captions",
    "overlays",
    "sfx",
    "bgm",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_workbench_manifest(plan: Any) -> dict[str, Any]:
    """Validate a workbench manifest plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. A present manifest must
    pin its version, take its timeline from the same source as the
    main composition, and declare exactly the six closed sections.
    An absent manifest passes only when the plan declares that the
    import entry point is unavailable.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "manifest plan must be a JSON object")],
            "sections": [],
            "manifest_version": None,
        }
    manifest_present = plan.get("manifest_present")
    if manifest_present is False:
        if plan.get("import_unavailable_declared") is not True:
            issues.append(
                _issue(
                    "import_availability_undeclared",
                    "without a manifest the plan must declare that "
                    "the workbench import entry point is unavailable",
                )
            )
        return {
            "verdict": "fail" if issues else "pass",
            "ok": not issues,
            "issues": issues,
            "sections": [],
            "manifest_version": None,
        }
    if manifest_present is not True:
        issues.append(
            _issue(
                "manifest_presence_undeclared",
                "plan must declare manifest_present as true or false",
            )
        )
        return {
            "verdict": "fail",
            "ok": False,
            "issues": issues,
            "sections": [],
            "manifest_version": None,
        }
    version = plan.get("manifest_version")
    if not isinstance(version, str) or not version.strip():
        issues.append(
            _issue(
                "manifest_version_unpinned",
                "manifest version must be a pinned non-empty string",
            )
        )
    if plan.get("timeline_same_source") is not True:
        issues.append(
            _issue(
                "timeline_not_same_source",
                "manifest timeline must come from the same source as the main composition",
            )
        )
    if plan.get("hand_copied_timeline") is True:
        issues.append(
            _issue(
                "hand_copied_timeline",
                "a hand-copied second timeline is not admitted",
            )
        )
    sections = plan.get("sections")
    if not isinstance(sections, list) or not sections:
        issues.append(
            _issue(
                "sections_missing",
                "manifest must declare a non-empty sections list",
            )
        )
        sections_out: list[str] = []
    else:
        sections_out = [s for s in sections if isinstance(s, str)]
        unknown = [s for s in sections_out if s not in MANIFEST_SECTIONS]
        if unknown:
            issues.append(
                _issue(
                    "unknown_section",
                    f"sections outside the closed vocabulary: {unknown}",
                )
            )
        missing = [s for s in MANIFEST_SECTIONS if s not in sections_out]
        if missing:
            issues.append(
                _issue(
                    "section_missing",
                    f"manifest omits required sections: {missing}",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "sections": sections_out,
        "manifest_version": version if isinstance(version, str) else None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_workbench_manifest(params.get("plan"))
    report_path = out_dir / "workbench_manifest.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_workbench_manifest_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.workbench_manifest_gate",
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
                "Workbench manifest gate: a present manifest must pin "
                "its version, share the main composition timeline "
                "source, and declare exactly the six closed sections; "
                "an absent manifest must declare the import entry "
                "point unavailable."
            ),
        )
    )
    return ["qa.workbench_manifest_gate"]


__all__ = [
    "MANIFEST_SECTIONS",
    "check_workbench_manifest",
    "register_workbench_manifest_gate_capabilities_once",
]
