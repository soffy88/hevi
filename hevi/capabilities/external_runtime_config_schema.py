"""External runtime configuration schema (``video.external_runtime_config_schema``).

Fake-level contract for the runtime configuration record
described in the Infinite Creation delta2 review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a settings record that
switches between a built-in runtime and external command-line
runtimes, records how each local installation is detected,
carries custom commands, and copies bridge configuration. The
contract certifies the shape of the record only. It launches
no runtime, spawns no process, copies no configuration anywhere,
and must never carry credentials: any credential-shaped field
fails the compile outright. Every compiled contract declares
``executed_here: false``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.agent_runtime_definition_gate import (
    check_agent_runtime_definitions,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_CREDENTIAL_KEY_PARTS = ("password", "token", "secret", "api_key", "api-key", "credential")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"video.external_runtime_config_schema: {detail}"}
    issue.update(extra)
    return issue


def _find_credential_fields(node: Any, path: str, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if any(part in lowered for part in _CREDENTIAL_KEY_PARTS):
                found.append(child)
            _find_credential_fields(value, child, found)
    elif isinstance(node, list):
        for position, value in enumerate(node):
            _find_credential_fields(value, f"{path}[{position}]", found)


def compile_external_runtime_config_contract(config: Any) -> dict[str, Any]:
    """Compile one external runtime configuration contract.

    ``config`` carries ``mode``, an optional ``builtin_runtime``,
    ``runtimes`` as judged by ``qa.agent_runtime_definition_gate``,
    and an optional ``mcp_config`` limited to the newline-delimited
    stdio bridge shape. Raises :class:`CapabilityError` on any
    shape violation or credential-shaped field. The returned
    contract records that nothing was executed here.
    """
    if not isinstance(config, dict):
        raise CapabilityError("runtime configuration must be an object")
    definition = {
        "mode": config.get("mode"),
        "builtin_runtime": config.get("builtin_runtime"),
        "runtimes": config.get("runtimes"),
    }
    report = check_agent_runtime_definitions(definition)
    if report["verdict"] == "fail":
        raise CapabilityError(
            "runtime definition failed validation: "
            + "; ".join(issue["detail"] for issue in report["issues"])
        )
    credential_fields: list[str] = []
    _find_credential_fields(config, "", credential_fields)
    if credential_fields:
        raise CapabilityError(
            "runtime configuration must never carry credentials: " + ", ".join(credential_fields)
        )
    mcp_config = config.get("mcp_config")
    if mcp_config is not None:
        if not isinstance(mcp_config, dict):
            raise CapabilityError("mcp_config must be an object when present")
        if mcp_config.get("transport") != "stdio":
            raise CapabilityError("mcp_config.transport must be 'stdio'")
        if mcp_config.get("framing") != "ndjson":
            raise CapabilityError("mcp_config.framing must be 'ndjson'")
    contract = {
        "mode": config.get("mode"),
        "builtin_runtime": config.get("builtin_runtime"),
        "runtime_names": report["runtime_names"],
        "runtime_count": report["runtime_count"],
        "mcp_config": mcp_config,
        "executed_here": False,
        "spawned_here": False,
        "no_runtime_launched": True,
        "verified_by": "contract only",
    }
    return {
        "ok": True,
        "verdict": "pass",
        "issues": [],
        "not_checked": ["runtime takeover effectiveness is unverified; nothing was launched"],
        "contract": contract,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_external_runtime_config_contract(params.get("config"))
    report_path = out_dir / "external_runtime_config_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "executed_here": False,
        },
    )


def register_external_runtime_config_schema_capabilities_once() -> list[str]:
    """Register ``video.external_runtime_config_schema`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.external_runtime_config_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "config": {"type": "object"},
                },
                "required": ["config"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "External runtime configuration schema (fake contract): a "
                "settings record switching between a built-in runtime and "
                "external command-line runtimes, with local detection, "
                "custom commands and stdio bridge configuration; nothing "
                "is launched and no credentials may appear."
            ),
        )
    )
    return ["video.external_runtime_config_schema"]


__all__ = [
    "compile_external_runtime_config_contract",
    "register_external_runtime_config_schema_capabilities_once",
]
