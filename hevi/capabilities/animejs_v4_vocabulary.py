"""Anime.js v4 timeline vocabulary gate (``qa.animejs_v4_vocabulary``).

Clean-room vocabulary gate only, restated from the public v4
source layout (package ``animejs`` 4.5.0, MIT). The v4 entry
points below were read off the v4 source exports (``animate``,
``createTimeline``, ``createTimer``, the ``engine`` singleton, the
``stagger``/``utils``/``eases`` helpers, and the ``svg``/``text``
namespaces); the easing string forms follow the v4 prefix rule
(``in``/``out``/``inOut``/``outIn`` composed with a base name) plus
the parametric forms. v3 spellings (``anime()``,
``anime.timeline()``, ``easeOutQuad``-style easing names, a ``3.x``
version) fail: v3 and v4 APIs are not compatible. No library code
is copied or executed here; this gate judges a plan only. See
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

ANIMEJS_V4_VERSION = "4.5.0"

# Entry points verified against the v4 source exports. Anything
# else (including the v3 ``anime`` entry point) is unknown here.
V4_ENTRY_POINTS: frozenset[str] = frozenset(
    {
        "animate",
        "createTimeline",
        "createTimer",
        "engine",
        "stagger",
        "utils",
        "eases",
        "svg",
        "text",
    }
)

_EASING_BASES = (
    "Quad",
    "Cubic",
    "Quart",
    "Quint",
    "Sine",
    "Expo",
    "Circ",
    "Back",
    "Elastic",
    "Bounce",
)
_EASING_PREFIXES = ("in", "out", "inOut", "outIn")

# 1 flat name + 40 composed names + 3 parametric forms = 44.
V4_EASINGS: frozenset[str] = frozenset(
    {"linear", "spring", "steps", "cubicBezier"}
    | {prefix + base for prefix in _EASING_PREFIXES for base in _EASING_BASES}
)

# Substrings that only ever appear in v3-style call sites. Checked
# against a declared code snippet only; "animate(" does not contain
# "anime(", so v4 call sites are not caught by the v3 marker.
V3_MARKERS: tuple[str, ...] = (
    "anime.timeline",
    "anime.stagger",
    "anime.easing",
    "anime.random",
    "anime(",
)


def animejs_v4_entry_points() -> frozenset[str]:
    """Return the closed v4 entry-point vocabulary."""
    return V4_ENTRY_POINTS


def animejs_v4_easings() -> frozenset[str]:
    """Return the closed v4 easing-string vocabulary."""
    return V4_EASINGS


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _easing_base(easing: str) -> str:
    return easing.split("(")[0].strip()


def check_animejs_v4_plan(plan: Any) -> dict[str, Any]:
    """Validate an Anime.js timeline plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Every animation must use
    a v4 entry point and a v4 easing string; a declared ``3.x``
    version and any v3 call-site marker fail.
    """
    issues: list[dict[str, Any]] = []
    anims_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "timeline plan must be a JSON object")
            ],
            "animations": [],
            "entry_points": len(V4_ENTRY_POINTS),
            "easings": len(V4_EASINGS),
            "v4_version": ANIMEJS_V4_VERSION,
        }
    version = plan.get("version")
    if version is not None:
        if not isinstance(version, str) or not version.startswith("4."):
            issues.append(
                _issue(
                    "v3_version",
                    "only Anime.js v4 plans pass this gate; "
                    "v3 and v4 APIs are not compatible",
                )
            )
    animations = plan.get("animations")
    if not isinstance(animations, list) or not animations:
        issues.append(
            _issue(
                "animations_missing",
                "plan must declare a non-empty animations list",
            )
        )
        animations = animations if isinstance(animations, list) else []
    for index, anim in enumerate(animations):
        label = f"animations[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(anim, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each animation must be an object")
            )
            anims_out.append(entry)
            continue
        entry_point = anim.get("entry_point")
        entry["entry_point"] = entry_point
        if not isinstance(entry_point, str) or entry_point not in V4_ENTRY_POINTS:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:unknown_entry_point",
                    f"{entry_point!r} is not a v4 entry point; "
                    "v3 spellings such as 'anime' fail here",
                )
            )
        easing = anim.get("easing")
        if easing is not None:
            if not isinstance(easing, str) or _easing_base(easing) not in V4_EASINGS:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:unknown_easing",
                        f"{easing!r} is not a v4 easing string; "
                        "v3 spellings such as 'easeOutQuad' fail here",
                    )
                )
        snippet = anim.get("code_snippet")
        if snippet is not None:
            if not isinstance(snippet, str):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:code_snippet_invalid",
                        "code_snippet must be a string when declared",
                    )
                )
            else:
                for marker in V3_MARKERS:
                    if marker in snippet:
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:v3_api_marker",
                                f"code snippet uses the v3 marker {marker!r}",
                            )
                        )
                        break
        if entry["issues"]:
            entry["ok"] = False
        anims_out.append(entry)
        issues.extend(entry["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "animations": anims_out,
        "entry_points": len(V4_ENTRY_POINTS),
        "easings": len(V4_EASINGS),
        "v4_version": ANIMEJS_V4_VERSION,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_animejs_v4_plan(params.get("plan"))
    report_path = out_dir / "animejs_v4_vocabulary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_animejs_v4_vocabulary_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.animejs_v4_vocabulary",
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
                "Anime.js v4 vocabulary gate: timeline plans must use "
                "v4 entry points and v4 easing strings; v3 spellings, "
                "v3 call-site markers, and 3.x versions fail."
            ),
        )
    )
    return ["qa.animejs_v4_vocabulary"]


__all__ = [
    "ANIMEJS_V4_VERSION",
    "V4_ENTRY_POINTS",
    "V4_EASINGS",
    "V3_MARKERS",
    "animejs_v4_entry_points",
    "animejs_v4_easings",
    "check_animejs_v4_plan",
    "register_animejs_v4_vocabulary_capabilities_once",
]
