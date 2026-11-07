"""Render lint (``qa.render_lint``).

Clean-room rewrite of the determinism-lint discipline behind
HeyGen's HyperFrames lint package (Apache-2.0; see
HYPERFRAMES_ATTRIBUTION.md). No code, text or configuration from
that repository is copied here. This module judges template and
composition *text* before render; it never executes the template.

Rules enforced on template text:

* No wall-clock reads: ``Date.now()``, ``new Date()``,
  ``performance.now()`` and ``requestAnimationFrame`` are
  forbidden in render code.
* No unseeded randomness: ``Math.random`` fails unless the
  template declares a seeded PRNG (a ``seed`` declaration or a
  named seeded generator such as ``mulberry32``).
* No fetch during render: ``fetch(`` / ``XMLHttpRequest`` fails
  unless the plan declares ``fetch_phase == "setup"``.
* Render variables (fps / width / height) must be assigned once:
  a second assignment fails as a re-lock.

Rules enforced on composition HTML:

* Every ``class="clip"`` element must carry ``data-start``,
  ``data-duration`` and ``data-track-index``; a missing attribute
  fails naming the element.

Failure contract: non-string template/HTML input raises
:class:`CapabilityError`. Violations return ``verdict: "fail"``
with named issues and line numbers where recoverable.
"""

from __future__ import annotations

import re
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    register,
)

_Registered = False

_WALL_CLOCK = (
    (re.compile(r"\bDate\s*\.\s*now\s*\("), "wall_clock_date_now"),
    (re.compile(r"\bnew\s+Date\s*\("), "wall_clock_new_date"),
    (re.compile(r"\bperformance\s*\.\s*now\s*\("), "wall_clock_performance_now"),
    (re.compile(r"\brequestAnimationFrame\s*\("), "wall_clock_raf"),
)
_SEEDED_MARKERS = ("mulberry32", "seeded", "PRNG", "seed =")
_VARIABLE_ASSIGN = re.compile(r"^\s*(?:const|let|var)?\s*(fps|width|height)\s*=", re.MULTILINE)


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def lint_template(text: Any, *, fetch_phase: str = "render") -> dict[str, Any]:
    """Lint template text for determinism violations."""
    if not isinstance(text, str):
        raise CapabilityError("template text must be a string")
    issues: list[dict[str, Any]] = []
    for pattern, code in _WALL_CLOCK:
        for match in pattern.finditer(text):
            issues.append(
                _issue(
                    code,
                    f"wall-clock read is forbidden during render: {match.group(0)!r}",
                    line=_line_no(text, match.start()),
                )
            )
    if "Math.random" in text and not any(marker in text for marker in _SEEDED_MARKERS):
        pos = text.index("Math.random")
        issues.append(
            _issue(
                "unseeded_random",
                "Math.random without a seeded PRNG declaration is forbidden; "
                "declare a seed (e.g. mulberry32) or remove the call",
                line=_line_no(text, pos),
            )
        )
    if fetch_phase != "setup":
        for token, code in (("fetch(", "render_fetch"), ("XMLHttpRequest", "render_xhr")):
            if token in text:
                issues.append(
                    _issue(
                        code,
                        f"{token} during render is forbidden; fetch only "
                        "during setup (fetch_phase='setup')",
                        line=_line_no(text, text.index(token)),
                    )
                )
    assignments: dict[str, list[int]] = {}
    for match in _VARIABLE_ASSIGN.finditer(text):
        assignments.setdefault(match.group(1), []).append(_line_no(text, match.start()))
    for name, lines in assignments.items():
        if len(lines) > 1:
            issues.append(
                _issue(
                    "variable_relock",
                    f"render variable {name!r} assigned {len(lines)} times; "
                    "fps/width/height must lock before frame 0",
                    variable=name,
                    lines=lines,
                )
            )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "issues": issues}


def lint_composition(html: Any) -> dict[str, Any]:
    """Lint composition HTML: every clip needs data-* timing attributes."""
    if not isinstance(html, str):
        raise CapabilityError("composition HTML must be a string")
    issues: list[dict[str, Any]] = []
    tag_re = re.compile(r"<[^>]*class\s*=\s*\"[^\"]*\bclip\b[^\"]*\"[^>]*>", re.IGNORECASE)
    for match in tag_re.finditer(html):
        tag = match.group(0)
        for attr in ("data-start", "data-duration", "data-track-index"):
            if attr not in tag:
                issues.append(
                    _issue(
                        "missing_data_attribute",
                        f"clip element is missing {attr}",
                        attribute=attr,
                        line=_line_no(html, match.start()),
                        element=tag[:120],
                    )
                )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "clips_checked": len(tag_re.findall(html)), "issues": issues}


def _render(params: dict[str, Any]) -> CapabilityResult:
    mode = params.get("mode", "template")
    if mode == "composition":
        result = lint_composition(params.get("html"))
    else:
        result = lint_template(
            params.get("text"), fetch_phase=str(params.get("fetch_phase", "render"))
        )
    return CapabilityResult(ok=result["verdict"] == "pass", output=result, files=[])


def register_render_lint_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.render_lint",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "html": {"type": "string"},
                    "mode": {"type": "string"},
                    "fetch_phase": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Render lint (HyperFrames determinism discipline, "
                "clean-room): no wall-clock reads, no unseeded "
                "randomness, no fetch during render, render variables "
                "lock before frame 0, and every clip element carries "
                "data-start/data-duration/data-track-index. Judges "
                "template/composition text only; never executes it."
            ),
            line="qa",
        )
    )
    return ["qa.render_lint"]
