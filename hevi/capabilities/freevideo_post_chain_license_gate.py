"""Post-chain license split gate (``qa.freevideo_post_chain_license_gate``).

The local post chain mixes licenses that must never be
pooled: frame interpolation, upscaling, and music are
permissively licensed, while the stem separator is
non-commercial and the Qwen image path is research-only.
In the reviewer's own words, a chain fails when a step
lacks a tool or a license, when the tool is unregistered,
when a license is unknown, when a non-commercial step
(Bandit stems) or a research-only step (Qwen image) is run
commercially, when a Qwen image step is not declared
research-only, or when ComfyUI GPL code is shipped into
hevi — the method may be learned, the code may not be
moved. The gate judges chain descriptions only; it never
runs a post step.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here.
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

# tool -> (license label, commercial allowed)
KNOWN_TOOLS: dict[str, tuple[str, bool]] = {
    "rife": ("MIT", True),
    "real_esrgan": ("BSD-3-Clause", True),
    "ace_step": ("MIT", True),
    "bandit_stems": ("CC BY-NC 4.0", False),
    "qwen_image": ("Qwen RESEARCH LICENSE", False),
}


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_freevideo_post_chain(chain: Any) -> dict[str, Any]:
    """Validate a FreeVideo-style post-chain license split.

    Verdicts are ``pass`` / ``fail`` only. A chain fails
    when it is not a non-empty list, when any step is not an
    object, when any step lacks a tool or a license, when a
    tool is unregistered, when a license is unknown, when a
    non-commercial or research-only step is run
    commercially, when a Qwen image step is not declared
    research-only, or when ComfyUI GPL code is shipped into
    hevi.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(chain, list) or not chain:
        return fail("chain_missing", "post chain must be a non-empty list")
    for position, step in enumerate(chain):
        if not isinstance(step, dict):
            return fail("step_not_object", f"post step {position} must be an object")
        tool = step.get("tool")
        if not isinstance(tool, str) or not tool:
            return fail("step_tool_missing", f"post step {position} must name a tool")
        if tool not in KNOWN_TOOLS:
            return fail(
                "step_tool_unregistered",
                f"post step {position} tool {tool!r} is not a registered post tool",
            )
        license_text = step.get("license")
        if not isinstance(license_text, str) or not license_text:
            return fail(
                "step_license_missing",
                f"post step {position} tool {tool!r} must record its license",
            )
        if license_text.strip().lower() == "unknown":
            return fail(
                "step_license_unknown",
                f"post step {position} tool {tool!r} has an unknown license",
            )
        _expected_license, commercial_allowed = KNOWN_TOOLS[tool]
        commercial = step.get("commercial") is True
        if commercial and not commercial_allowed:
            return fail(
                "step_commercial_banned",
                f"post step {position} tool {tool!r} is not licensed for commercial use",
            )
        if tool == "qwen_image" and step.get("research_only") is not True:
            return fail(
                "qwen_image_not_research_only",
                "a Qwen image step must be declared research-only",
            )
        if step.get("ships_gpl_code_into_hevi") is True:
            return fail(
                "gpl_code_not_moved",
                "ComfyUI GPL code is learned from, never moved into hevi",
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
    report = check_freevideo_post_chain(params.get("chain"))
    report_path = out_dir / "freevideo_post_chain_license_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_post_chain_license_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_post_chain_license_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "chain": {"type": "array"},
                },
                "required": ["chain"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "FreeVideo post-chain license split gate: RIFE, "
                "Real-ESRGAN, and ACE-Step run commercially; Bandit "
                "stems stay non-commercial; Qwen image stays "
                "research-only; ComfyUI GPL code is never moved into hevi."
            ),
        )
    )
    return ["qa.freevideo_post_chain_license_gate"]


__all__ = [
    "KNOWN_TOOLS",
    "check_freevideo_post_chain",
    "register_freevideo_post_chain_license_gate_capabilities_once",
]
