"""Krita file contract gate (``qa.krita_file_contract_gate``).

Clean-room method gate only. Krita is a desktop painting
application (Qt/KDE, GPL-3.0); there is no SDK to install, no
brush bundle is packed, and no Krita code is copied here. A
``.kra`` handling plan must declare the ZIP container shape,
keep the source file untouched, and keep exports separate from
the source. Two export paths are recognized, both restated in
our own words: a command-line export, and an in-application
plugin path (the libkis API, running inside a Krita GUI
session). This gate judges the plan only and touches no file:
``executed_here`` is always false and no desktop application
is launched, installed, or probed here. Real painting and
export are a separate real-machine case. See
FIFTEEN_TOOLS_ATTRIBUTION.md.
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

# Krita's own license, recorded from the repository's license
# text. GPL items are file-contract/method reference only here.
KRITA_LICENSE = "GPL-3.0"

# A .kra file is a ZIP container. The merged preview image is the
# read-only index's evidence that the container is intact.
CONTAINER_FORMAT = "zip"
MERGED_PREVIEW = "mergedimage.png"

# The only .kra handling modes this gate recognizes.
HANDLING_MODES = ("read_only_index", "cli_export", "plugin")

# This gate's own whitelist for command-line export parameters.
# It is a plan-shape whitelist, not Krita's command-line surface.
CLI_EXPORT_ALLOWED_PARAMETERS = frozenset(
    {"output_path", "format", "width", "height", "frame_range"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_krita_file_contract(plan: Any) -> dict[str, Any]:
    """Validate a .kra handling plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. The plan must name a
    source, declare the ZIP container, promise the source is
    never overwritten, and pick one recognized handling mode.
    Nothing here reads, writes, or exports any file.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", ".kra handling plan must be a JSON object")
            ],
            "executed_here": False,
            "desktop_operation": "real_machine_case",
            "source_never_modified": True,
        }
    source_ref = plan.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        issues.append(
            _issue("source_ref_missing", "plan must name a .kra source_ref")
        )
    if plan.get("source_preserved") is not True:
        issues.append(
            _issue(
                "source_not_preserved",
                "the .kra source file must be declared preserved; "
                "handling never overwrites the source",
            )
        )
    if plan.get("container") != CONTAINER_FORMAT:
        issues.append(
            _issue(
                "container_not_zip",
                "a .kra file is a ZIP container; the plan must "
                'declare container "zip"',
            )
        )
    if plan.get("sdk_installed") is True:
        issues.append(
            _issue(
                "no_sdk_to_install",
                "Krita ships no SDK; a plan must not claim one "
                "was installed here",
            )
        )
    if plan.get("brush_bundle_bundled") is True:
        issues.append(
            _issue(
                "brush_bundle_not_bundled",
                "no Krita brush bundle is packed into this repository",
            )
        )
    if plan.get("krita_installed_here") is True:
        issues.append(
            _issue(
                "desktop_app_not_installed_here",
                "no desktop application is installed or launched here",
            )
        )
    mode = plan.get("mode")
    if mode not in HANDLING_MODES:
        issues.append(
            _issue(
                "mode_unknown",
                "mode must be one of read_only_index, cli_export, plugin",
            )
        )
    elif mode == "read_only_index":
        if plan.get("mergedimage_png") is not True:
            issues.append(
                _issue(
                    "mergedimage_missing",
                    "a read-only index must declare the merged preview "
                    f"({MERGED_PREVIEW}) present in the container",
                )
            )
    elif mode == "cli_export":
        params = plan.get("export_parameters")
        if not isinstance(params, dict):
            issues.append(
                _issue(
                    "export_parameters_missing",
                    "cli_export mode must declare export_parameters",
                )
            )
        else:
            unknown = sorted(set(params) - CLI_EXPORT_ALLOWED_PARAMETERS)
            if unknown:
                issues.append(
                    _issue(
                        "export_parameter_not_whitelisted",
                        "export parameters outside this gate's whitelist: "
                        + ", ".join(unknown),
                    )
                )
            output_path = params.get("output_path")
            if not isinstance(output_path, str) or not output_path:
                issues.append(
                    _issue(
                        "export_output_missing",
                        "cli_export mode must declare an export output_path",
                    )
                )
            elif output_path == source_ref:
                issues.append(
                    _issue(
                        "export_overwrites_source",
                        "the export output must be separate from the "
                        ".kra source file",
                    )
                )
    elif mode == "plugin":
        if plan.get("runs_inside_krita") is not True:
            issues.append(
                _issue(
                    "plugin_requires_gui_session",
                    "the plugin path runs inside a Krita GUI session; "
                    "the plan must declare runs_inside_krita",
                )
            )
        if plan.get("uses_libkis") is not True:
            issues.append(
                _issue(
                    "plugin_requires_libkis",
                    "the plugin path uses the in-application libkis "
                    "API; the plan must declare uses_libkis",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "mode": mode if mode in HANDLING_MODES else None,
        "executed_here": False,
        "desktop_operation": "real_machine_case",
        "source_never_modified": True,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_krita_file_contract(params.get("plan"))
    report_path = out_dir / "krita_file_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_krita_file_contract_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.krita_file_contract_gate",
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
                "Krita file contract gate: a .kra handling plan must "
                "declare the ZIP container, preserve the source, and "
                "pick one recognized mode (read-only index, CLI "
                "export, or in-application plugin); nothing is read, "
                "written, or exported here."
            ),
        )
    )
    return ["qa.krita_file_contract_gate"]


__all__ = [
    "CLI_EXPORT_ALLOWED_PARAMETERS",
    "CONTAINER_FORMAT",
    "HANDLING_MODES",
    "KRITA_LICENSE",
    "MERGED_PREVIEW",
    "check_krita_file_contract",
    "register_krita_file_contract_gate_capabilities_once",
]
