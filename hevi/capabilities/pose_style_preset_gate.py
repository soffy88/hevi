"""Style preset gate (``qa.pose_style_preset_gate``).

Style preset discipline for the pose gallery's twelve
claimed art styles. Honesty first: the upstream README
claims 12 style presets, but the preset table and the
prompt-assembly code were never checked item by item, so
no preset name is treated as verified upstream here. A
preset must declare its source as ``hevi-local`` (defined
here) or ``upstream-unverified`` (claimed upstream, name
not verified); a preset that claims plain ``upstream``
provenance fails. A full pack holds exactly 12 presets,
the README-claimed count, with unique names and a
non-empty Chinese prompt template each.
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

PRESET_SOURCES: frozenset[str] = frozenset({"hevi-local", "upstream-unverified"})
FULL_PACK_SIZE = 12


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_pose_style_preset(preset: Any) -> dict[str, Any]:
    """Validate one style preset declaration.

    Verdicts are ``pass`` / ``fail`` only. A preset fails
    when it has no name, no Chinese prompt template, or a
    source outside ``hevi-local`` / ``upstream-unverified``.
    Plain ``upstream`` provenance is refused: the twelve
    upstream preset names were never verified.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(preset, dict):
        return fail("preset_not_object", "style preset must be a JSON object")
    name = preset.get("name")
    if not isinstance(name, str) or not name.strip():
        return fail("preset_name_missing", "style preset must carry a non-empty name")
    if preset.get("source") not in PRESET_SOURCES:
        return fail(
            "preset_source_unknown",
            "style preset source must be hevi-local or "
            f"upstream-unverified, got {preset.get('source')!r}; plain "
            "upstream provenance is refused because the twelve "
            "upstream preset names were never verified",
        )
    template = preset.get("prompt_template_zh")
    if not isinstance(template, str) or not template.strip():
        return fail(
            "prompt_template_missing",
            "style preset must carry a non-empty Chinese prompt template",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "name": name,
        "source": preset.get("source"),
        "executed_here": False,
    }


def check_pose_style_preset_pack(pack: Any) -> dict[str, Any]:
    """Validate a full style preset pack (exactly 12 presets)."""
    if not isinstance(pack, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("pack_not_object", "style preset pack must be a JSON object")],
            "executed_here": False,
        }
    presets = pack.get("presets")
    if not isinstance(presets, list):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("presets_missing", "pack must carry a presets list")],
            "executed_here": False,
        }
    if len(presets) != FULL_PACK_SIZE:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "pack_size_mismatch",
                    f"a full style preset pack holds {FULL_PACK_SIZE} presets "
                    f"(README-claimed count), got {len(presets)}",
                )
            ],
            "executed_here": False,
        }
    names = [p.get("name") if isinstance(p, dict) else None for p in presets]
    if len(set(names)) != len(names):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("preset_names_not_unique", "preset names in a pack must be unique")],
            "executed_here": False,
        }
    for preset in presets:
        verdict = check_pose_style_preset(preset)
        if verdict["verdict"] != "pass":
            return verdict
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "count": FULL_PACK_SIZE,
        "names": names,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if "pack" in params and params.get("pack") is not None:
        report = check_pose_style_preset_pack(params.get("pack"))
    else:
        report = check_pose_style_preset(params.get("preset"))
    report_path = out_dir / "pose_style_preset_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_style_preset_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_style_preset_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "preset": {"type": "object"},
                    "pack": {"type": "object"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery style preset gate: twelve-preset full "
                "packs, sources hevi-local or upstream-unverified "
                "only; plain upstream provenance is refused because "
                "the upstream preset names were never verified."
            ),
        )
    )
    return ["qa.pose_style_preset_gate"]


__all__ = [
    "FULL_PACK_SIZE",
    "PRESET_SOURCES",
    "check_pose_style_preset",
    "check_pose_style_preset_pack",
    "register_pose_style_preset_gate_capabilities_once",
]
