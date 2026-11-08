"""Agent runtime definition gate (``qa.agent_runtime_definition_gate``).

Clean-room restatement of the runtime-definition discipline
recorded in the Infinite Creation delta2 review (see
``INFINITE_CREATION_ATTRIBUTION.md``): an agent-driven video
pipeline may be driven by a built-in runtime or by an external
command-line agent, switched from a settings record. Every
runtime in that record must be fully defined -- which command
runs it, how a local installation is detected, whether its
bridge configuration can be copied, and the fact that accounts
and sign-in state stay with each command-line tool itself and
never travel through the pipeline's own configuration. A claim
that a runtime can draft and register new skills is never
accepted here: no verified implementation of that exists in the
reviewed material. This gate judges definition records only:
it launches no runtime, spawns no process, and handles no
credentials.
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

_Registered = False

# Identifiers of the external command-line runtimes named in the
# delta2 review, plus the built-in runtime identifier. These are
# factual tool identifiers, not copied prose; the closed list
# keeps a definition from inventing a runtime it cannot name.
RUNTIME_NAMES = (
    "claude",
    "codex",
    "cursor-agent",
    "gemini",
    "hermes",
    "qwen",
    "grok",
    "opencode",
    "qoder",
)
BUILTIN_RUNTIME = "openclaude"
MODES = ("builtin", "external", "mixed")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.agent_runtime_definition_gate: {detail}"}
    issue.update(extra)
    return issue


def check_agent_runtime_definitions(definition: Any) -> dict[str, Any]:
    """Judge one agent runtime definition record.

    ``definition`` carries ``runtimes`` (each with ``name``,
    ``cli_command``, ``detection``, ``mcp_config_copy`` and
    ``account_via_own_cli``), an optional ``mode`` and, for
    built-in mode, ``builtin_runtime``. Custom runtimes use
    ``name`` ``"custom"`` with a non-empty ``custom_command``.
    Verdict ``pass`` means every runtime is fully defined, no
    credentials travel through the configuration, and no
    skill-drafting power is claimed.
    """
    if not isinstance(definition, dict):
        raise CapabilityError("runtime definition must be an object")
    issues: list[dict[str, Any]] = []
    runtimes = definition.get("runtimes")
    if not isinstance(runtimes, list) or not runtimes:
        raise CapabilityError("runtime definition requires a non-empty runtimes list")
    mode = definition.get("mode")
    if mode is not None and mode not in MODES:
        issues.append(_issue("mode_invalid", f"mode must be one of {MODES}"))
    if mode == "builtin" and definition.get("builtin_runtime") != BUILTIN_RUNTIME:
        issues.append(
            _issue(
                "builtin_runtime_mismatch",
                f"builtin mode requires builtin_runtime {BUILTIN_RUNTIME!r}",
            )
        )
    seen_names: set[str] = set()
    for position, runtime in enumerate(runtimes):
        if not isinstance(runtime, dict):
            issues.append(_issue("runtime_not_object", f"runtime {position} is not an object"))
            continue
        name = runtime.get("name")
        if name == "custom":
            if (
                not isinstance(runtime.get("custom_command"), str)
                or not runtime["custom_command"].strip()
            ):
                issues.append(
                    _issue(
                        "custom_command_missing",
                        f"custom runtime {position} requires a non-empty custom_command",
                    )
                )
        elif name not in RUNTIME_NAMES:
            issues.append(
                _issue(
                    "runtime_unknown",
                    f"runtime {position} name {name!r} is not one of the known runtimes",
                    runtime=position,
                )
            )
        if isinstance(name, str):
            if name in seen_names:
                issues.append(_issue("runtime_duplicate", f"runtime {name!r} is defined twice"))
            seen_names.add(name)
        if not isinstance(runtime.get("cli_command"), str) or not runtime["cli_command"].strip():
            issues.append(
                _issue("cli_command_missing", f"runtime {position} requires a cli_command")
            )
        if not isinstance(runtime.get("detection"), str) or not runtime["detection"].strip():
            issues.append(
                _issue(
                    "detection_missing",
                    f"runtime {position} requires a detection declaration for local installation checks",
                )
            )
        if not isinstance(runtime.get("mcp_config_copy"), bool):
            issues.append(
                _issue(
                    "mcp_config_copy_missing",
                    f"runtime {position} must declare mcp_config_copy as a boolean",
                )
            )
        if runtime.get("account_via_own_cli") is not True:
            issues.append(
                _issue(
                    "account_routing_invalid",
                    f"runtime {position} must route accounts through its own command-line tool",
                )
            )
        if runtime.get("credentials_in_config") is True:
            issues.append(
                _issue(
                    "credentials_in_config",
                    f"runtime {position} must never carry credentials in pipeline configuration",
                )
            )
        if runtime.get("generates_skill") is True:
            issues.append(
                _issue(
                    "unverified_skill_generation",
                    f"runtime {position} claims skill drafting, which has no verified implementation",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": ["takeover effectiveness is unverified; no runtime was launched"],
        "runtime_count": len(seen_names),
        "runtime_names": sorted(seen_names),
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_agent_runtime_definitions(params.get("definition"))
    report_path = out_dir / "agent_runtime_definition.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_agent_runtime_definition_gate_capabilities_once() -> list[str]:
    """Register ``qa.agent_runtime_definition_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.agent_runtime_definition_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "definition": {"type": "object"},
                },
                "required": ["definition"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Agent runtime definition gate: every runtime must declare "
                "its command, local detection, bridge-configuration copying "
                "and own-tool account routing; no credentials may travel "
                "through pipeline configuration and no skill drafting may "
                "be claimed."
            ),
        )
    )
    return ["qa.agent_runtime_definition_gate"]


__all__ = [
    "BUILTIN_RUNTIME",
    "MODES",
    "RUNTIME_NAMES",
    "check_agent_runtime_definitions",
    "register_agent_runtime_definition_gate_capabilities_once",
]
