"""Premium composition gate (``qa.premium_composition_gate``).

Clean-room rewrite of a *method* only: a knowledge-film shot is
built from three composition layers (base picture, moving element,
information overlay), a shot never sits still longer than a caller
set limit, and on-screen words stay short and few. No text, code, or
asset from any outside repository is copied here. See
VIBE_KNOWLEDGE_ATTRIBUTION.md.

Thresholds are caller parameters recorded in the report; the gate
ships no baked-in taste defaults beyond the documented fallbacks,
which the caller may always override.
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

LAYERS = ("base", "motion", "info")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_premium_composition(plan: Any) -> dict[str, Any]:
    """Judge one composition plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    shots_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "composition plan must be a JSON object")
            ],
            "shots": [],
            "thresholds_applied": {},
        }
    max_still_s = plan.get("max_still_s", 3.0)
    if not _is_number(max_still_s) or max_still_s <= 0:
        issues.append(
            _issue(
                "max_still_s_invalid",
                "max_still_s must be a positive number of seconds",
            )
        )
        max_still_s = 3.0
    max_chars = plan.get("max_on_screen_chars", 8)
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
        issues.append(
            _issue(
                "max_on_screen_chars_invalid",
                "max_on_screen_chars must be a positive whole number",
            )
        )
        max_chars = 8
    max_groups = plan.get("max_on_screen_groups", 2)
    if not isinstance(max_groups, int) or isinstance(max_groups, bool) or max_groups < 1:
        issues.append(
            _issue(
                "max_on_screen_groups_invalid",
                "max_on_screen_groups must be a positive whole number",
            )
        )
        max_groups = 2
    min_layers = plan.get("min_layers", 2)
    if not isinstance(min_layers, int) or isinstance(min_layers, bool) or not 1 <= min_layers <= 3:
        issues.append(
            _issue(
                "min_layers_invalid",
                "min_layers must be a whole number from 1 to 3",
            )
        )
        min_layers = 2
    thresholds = {
        "max_still_s": max_still_s,
        "max_on_screen_chars": max_chars,
        "max_on_screen_groups": max_groups,
        "min_layers": min_layers,
    }
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append(
            _issue("shots_missing", "plan must declare a non-empty shots list")
        )
        shots = shots if isinstance(shots, list) else []
    for index, shot in enumerate(shots):
        label = f"shots[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(shot, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each shot must be an object")
            )
            shots_out.append(entry)
            continue
        layers = shot.get("layers")
        if not isinstance(layers, list):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:layers_missing",
                    "each shot must declare a layers list drawn from "
                    "base, motion, info",
                )
            )
        else:
            unknown = [layer for layer in layers if layer not in LAYERS]
            if unknown:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:layer_unknown",
                        f"unknown composition layers: {unknown}",
                    )
                )
            present = len(set(layers) & set(LAYERS))
            if present < min_layers:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:layers_too_few",
                        f"shot uses {present} composition layers, "
                        f"fewer than the required {min_layers}",
                    )
                )
        still_s = shot.get("longest_still_s")
        if still_s is not None:
            if not _is_number(still_s) or still_s < 0:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:still_invalid",
                        "longest_still_s must be a non-negative number",
                    )
                )
            elif still_s > max_still_s:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:still_too_long",
                        f"longest still run is {still_s}s, over the "
                        f"{max_still_s}s limit",
                    )
                )
        texts = shot.get("on_screen_text")
        if texts is not None:
            if not isinstance(texts, list):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:on_screen_text_invalid",
                        "on_screen_text must be a list",
                    )
                )
            else:
                groups = set()
                for text in texts:
                    if not isinstance(text, dict):
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:on_screen_text_not_object",
                                "each on-screen text must be an object",
                            )
                        )
                        continue
                    wording = text.get("text")
                    if not isinstance(wording, str) or not wording.strip():
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:on_screen_text_empty",
                                "each on-screen text must carry wording",
                            )
                        )
                        continue
                    if len(wording) > max_chars:
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:on_screen_text_too_long",
                                f"on-screen wording {wording!r} is "
                                f"{len(wording)} characters, over the "
                                f"{max_chars} limit",
                            )
                        )
                    group = text.get("group")
                    if isinstance(group, str) and group.strip():
                        groups.add(group.strip())
                if len(groups) > max_groups:
                    entry["ok"] = False
                    entry["issues"].append(
                        _issue(
                            f"{label}:on_screen_groups_too_many",
                            f"shot shows {len(groups)} on-screen groups, "
                            f"over the {max_groups} limit",
                        )
                    )
        if entry["issues"]:
            entry["ok"] = False
            issues.extend(entry["issues"])
        shots_out.append(entry)
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "shots": shots_out,
        "thresholds_applied": thresholds,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_premium_composition(params.get("plan"))
    report_path = out_dir / "premium_composition.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_premium_composition_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.premium_composition_gate",
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
            description=(
                "Premium composition gate: shots use at least two of "
                "three composition layers, still runs stay within a "
                "caller-set limit, and on-screen wording stays short "
                "and few."
            ),
        )
    )
    return ["qa.premium_composition_gate"]


__all__ = [
    "check_premium_composition",
    "register_premium_composition_gate_capabilities_once",
]
