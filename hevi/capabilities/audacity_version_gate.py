"""Audacity version and interface gate (``qa.audacity_version_gate``).

Clean-room method gate only. Audacity is a desktop audio
editor (GPLv3, with some files under GPLv2, per the
repository's own LICENSE text); no Audacity code is copied
here and no desktop application is installed. The version
line matters for automation: the 4.x line, rewritten on a
new UI toolkit with a new project format, currently offers
no official scripting entry point, while the 3.x line keeps
its macro and script-pipe automation. A plan must declare
its version honestly: a scripting or effect-chain claim
against 4.x fails closed, and a 3.x scripting claim must name
its interface. This gate judges the plan only and executes
nothing: ``executed_here`` is always false. Real audio work
is a separate real-machine case, and the effect-chain
contract itself is a deferred case. See
FIFTEEN_TOOLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# License as stated in the repository's own LICENSE text: the
# first line names GPLv3, with some files under GPLv2.
AUDACITY_LICENSE = "GPLv3 (some files GPLv2), per in-repo LICENSE.txt"

# The 4.x line has no official scripting entry point; the
# macro manager and script pipe were removed and are described
# as returning later. The 3.x line keeps them.
SCRIPTING_REMOVED_MAJOR = 4
LEGACY_SCRIPTING_INTERFACES = ("macro", "mod_script_pipe")

# Project format per major line, restated from the version
# notes: 4.x uses the new format, 3.x the previous one.
PROJECT_FORMAT_BY_MAJOR = {3: "aup3", 4: "aup4"}


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _parse_major(text: Any) -> int | None:
    if not isinstance(text, str) or not text.strip():
        return None
    match = re.match(r"v?(\d+)", text.strip())
    return int(match.group(1)) if match else None


def check_audacity_version(plan: Any) -> dict[str, Any]:
    """Validate an Audacity version/interface plan; never raises.

    Verdicts are ``pass`` / ``fail`` only. Version 4.x plans
    must not claim scripting or an effect chain; version 3.x
    scripting claims must name their interface.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "plan_not_object",
                    "Audacity plan must be a JSON object",
                )
            ],
            "executed_here": False,
            "desktop_operation": "real_machine_case",
        }
    major = _parse_major(plan.get("audacity_version"))
    if major is None:
        issues.append(
            _issue(
                "version_unparseable",
                "plan must declare an audacity_version such as 4.0.2",
            )
        )
    elif major < 3:
        issues.append(
            _issue(
                "version_too_old",
                "versions before the 3.x line are outside this gate",
            )
        )
    elif major >= SCRIPTING_REMOVED_MAJOR:
        if plan.get("scripting") is True:
            issues.append(
                _issue(
                    "audacity4_no_scripting",
                    "the 4.x line currently offers no official "
                    "scripting entry point; a scripting claim "
                    "against 4.x fails closed",
                )
            )
        effect_chain = plan.get("effect_chain")
        if isinstance(effect_chain, list) and effect_chain:
            issues.append(
                _issue(
                    "audacity4_effect_chain_unavailable",
                    "an effect chain cannot be driven against the "
                    "4.x line here; the effect-chain contract is a "
                    "separate case and is 3.x-only",
                )
            )
        project_format = plan.get("project_format")
        if project_format is not None and project_format != "aup4":
            issues.append(
                _issue(
                    "audacity4_format_mismatch",
                    "the 4.x line uses the aup4 project format",
                )
            )
    else:  # major == 3
        if plan.get("scripting") is True:
            interface = plan.get("scripting_interface")
            if interface not in LEGACY_SCRIPTING_INTERFACES:
                issues.append(
                    _issue(
                        "legacy_scripting_interface_undeclared",
                        "a 3.x scripting claim must name its interface: "
                        "macro or mod_script_pipe",
                    )
                )
        project_format = plan.get("project_format")
        if project_format is not None and project_format != "aup3":
            issues.append(
                _issue(
                    "audacity3_format_mismatch",
                    "the 3.x line uses the aup3 project format",
                )
            )
    if plan.get("effects_executed_here") is True:
        issues.append(
            _issue(
                "nothing_executed_here",
                "no audio effect is executed by this gate",
            )
        )
    if plan.get("companion_fork_built") is True:
        issues.append(
            _issue(
                "companion_fork_not_built",
                "no third-party companion fork is compiled here; "
                "third-party bridges are unproven and must not be "
                "presented as official",
            )
        )
    scripting_available = bool(
        major == 3
        and plan.get("scripting") is True
        and plan.get("scripting_interface") in LEGACY_SCRIPTING_INTERFACES
    )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "major": major,
        "scripting_available": scripting_available,
        "executed_here": False,
        "desktop_operation": "real_machine_case",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_audacity_version(params.get("plan"))
    report_path = out_dir / "audacity_version.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_audacity_version_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.audacity_version_gate",
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
                "Audacity version and interface gate: 4.x plans "
                "must not claim scripting or an effect chain, 3.x "
                "scripting claims must name their interface, and "
                "no companion fork is compiled here."
            ),
        )
    )
    return ["qa.audacity_version_gate"]


__all__ = [
    "AUDACITY_LICENSE",
    "LEGACY_SCRIPTING_INTERFACES",
    "PROJECT_FORMAT_BY_MAJOR",
    "SCRIPTING_REMOVED_MAJOR",
    "check_audacity_version",
    "register_audacity_version_gate_capabilities_once",
]
