"""React Three Fiber variant gate (``qa.r3f_variant_gate``).

Clean-room method gate only. React Three Fiber is a React
renderer for Three.js scenes; it is not the same thing as a
plain Three.js template. A plan that claims the React Three
Fiber variant must declare the matching combination: React in
the v9 peer range, a Three.js version at or above the v9
floor, and a stable v9 renderer version. A plain Three.js plan
must not carry React Three Fiber declarations. This gate
judges declarations only: no React build chain exists here,
no scene is rendered, and ``executed_here`` is always false.
Real rendering is a separate real-machine case. See
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

# Version floor and range for the stable React Three Fiber v9
# line, restated from its peer requirements: React >= 19 and
# below 19.4, Three.js >= 0.156, renderer major version 9.
REACT_MINIMUM = (19, 0)
REACT_MAXIMUM_EXCLUSIVE = (19, 4)
THREE_MINIMUM = (0, 156)
R3F_STABLE_MAJOR = 9

RENDERERS = ("r3f", "plain_three")

_PRERELEASE_RE = re.compile(r"(alpha|beta|rc|preview|dev)", re.IGNORECASE)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def parse_version_text(text: Any) -> tuple[int, ...] | None:
    """Parse a version string into an integer tuple, or None.

    Accepts leading ``v``/``r`` markers (``r169``) and trailing
    pre-release suffixes. Returns None for anything unparseable.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip().lstrip("vrVR")
    head = re.split(r"[-+]", cleaned, maxsplit=1)[0]
    parts = head.split(".")
    numbers: list[int] = []
    for part in parts:
        match = re.match(r"(\d+)", part)
        if match is None:
            return None
        numbers.append(int(match.group(1)))
    return tuple(numbers) if numbers else None


def _is_prerelease(text: Any) -> bool:
    return isinstance(text, str) and _PRERELEASE_RE.search(text) is not None


def check_r3f_variant(plan: Any) -> dict[str, Any]:
    """Validate a renderer-variant declaration; never raises.

    Verdicts are ``pass`` / ``fail`` only. The ``r3f`` variant
    needs the full matching combination; the ``plain_three``
    variant must carry no React Three Fiber declarations.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "plan_not_object",
                    "renderer variant plan must be a JSON object",
                )
            ],
            "executed_here": False,
            "render_bridge": "real_machine_case",
        }
    renderer = plan.get("renderer")
    if renderer not in RENDERERS:
        issues.append(
            _issue(
                "renderer_unknown",
                "renderer must be one of r3f, plain_three",
            )
        )
    elif renderer == "r3f":
        react = parse_version_text(plan.get("react_version"))
        if react is None:
            issues.append(
                _issue(
                    "react_version_missing",
                    "the r3f variant must declare react_version",
                )
            )
        elif not (REACT_MINIMUM <= react[:2] < REACT_MAXIMUM_EXCLUSIVE):
            issues.append(
                _issue(
                    "react_version_out_of_range",
                    "the r3f v9 line needs React >= 19 and below 19.4",
                )
            )
        three = parse_version_text(plan.get("three_version"))
        if three is None:
            issues.append(
                _issue(
                    "three_version_missing",
                    "the r3f variant must declare three_version",
                )
            )
        elif three[:2] < THREE_MINIMUM:
            issues.append(
                _issue(
                    "three_version_too_old",
                    "the r3f v9 line needs Three.js >= 0.156",
                )
            )
        r3f_text = plan.get("r3f_version")
        r3f = parse_version_text(r3f_text)
        if r3f is None:
            issues.append(
                _issue(
                    "r3f_version_missing",
                    "the r3f variant must declare r3f_version",
                )
            )
        elif _is_prerelease(r3f_text):
            issues.append(
                _issue(
                    "r3f_prerelease_not_stable",
                    "pre-release renderer versions are not the stable "
                    "line and must not be written into defaults",
                )
            )
        elif r3f[0] != R3F_STABLE_MAJOR:
            issues.append(
                _issue(
                    "r3f_version_not_v9",
                    "the stable renderer line declared here is major "
                    "version 9",
                )
            )
        if plan.get("rendered_here") is True:
            issues.append(
                _issue(
                    "nothing_rendered_here",
                    "no scene is rendered by this gate",
                )
            )
    else:  # plain_three
        if plan.get("r3f_version") is not None:
            issues.append(
                _issue(
                    "plain_three_mislabelled_r3f",
                    "a plain Three.js plan must not declare r3f_version",
                )
            )
        if plan.get("react_version") is not None:
            issues.append(
                _issue(
                    "plain_three_mislabelled_r3f",
                    "a plain Three.js plan must not declare react_version",
                )
            )
        if plan.get("claims_r3f") is True:
            issues.append(
                _issue(
                    "plain_three_mislabelled_r3f",
                    "a plain Three.js plan must not claim to be the "
                    "React Three Fiber variant",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "renderer": renderer if renderer in RENDERERS else None,
        "react_range": ">=19,<19.4",
        "three_minimum": "0.156",
        "stable_r3f_major": R3F_STABLE_MAJOR,
        "executed_here": False,
        "render_bridge": "real_machine_case",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_r3f_variant(params.get("plan"))
    report_path = out_dir / "r3f_variant.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_r3f_variant_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.r3f_variant_gate",
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
                "React Three Fiber variant gate: the r3f variant "
                "needs React >= 19 below 19.4, Three.js >= 0.156, "
                "and stable renderer major 9; a plain Three.js plan "
                "must carry no React Three Fiber declarations."
            ),
        )
    )
    return ["qa.r3f_variant_gate"]


__all__ = [
    "R3F_STABLE_MAJOR",
    "REACT_MAXIMUM_EXCLUSIVE",
    "REACT_MINIMUM",
    "RENDERERS",
    "THREE_MINIMUM",
    "check_r3f_variant",
    "parse_version_text",
    "register_r3f_variant_gate_capabilities_once",
]
