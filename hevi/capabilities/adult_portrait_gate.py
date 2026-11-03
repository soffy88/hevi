"""Adult-portrait gate (``qa.adult_portrait_gate``).

Hard intercept, never a warning: a portrait plan must declare an
adult age, and no minor-indicating wording may appear anywhere in
it.  The age must be an integer (or a digit string) of at least
18, supplied as ``age_years``, or an exact declaration such as
``25岁`` / ``25 years old`` in ``age_declaration``.  A missing,
fuzzy, or under-18 age fails.  Any minor-indicating term in the
plan text fails even when an adult age is declared -- the gate
does not downgrade to a warning.

The minor-indicator list is deliberately conservative: it names
childhood and school-age statuses only.  The ambiguous word
``少女`` is deliberately NOT in the list (it is used for adults
too); an undeclared age still fails on its own, so the ambiguity
cannot be used to bypass the declaration requirement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

MIN_AGE = 18

MINOR_TERMS: frozenset[str] = frozenset(
    {
        "未成年",
        "儿童",
        "幼儿",
        "少年",
        "小学生",
        "中学生",
        "高中生",
        "青少年",
        "婴儿",
        "幼儿园",
        "child",
        "children",
        "minor",
        "teenager",
        "underage",
        "schoolgirl",
        "schoolboy",
        "kid",
        "toddler",
        "baby",
    }
)

_AGE_DECL_RE = re.compile(r"(\d+)\s*(?:岁|years?\s*old|yo)\b", re.IGNORECASE)


def _declared_age(plan: dict[str, Any]) -> int | None:
    raw = plan.get("age_years")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    decl = plan.get("age_declaration")
    if isinstance(decl, str):
        match = _AGE_DECL_RE.search(decl)
        if match:
            return int(match.group(1))
    return None


def _plan_text(plan: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("subject_text", "anchoring", "environment", "scene", "notes", "text"):
        value = plan.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def check_adult_portrait(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge the adult-age declaration and scan for minor wording."""
    if not isinstance(plan, dict):
        raise CapabilityError("adult-portrait plan must be an object")
    issues: list[str] = []
    age = _declared_age(plan)
    if age is None:
        issues.append(
            "age_undeclared: plan must declare an adult age "
            "(age_years integer, or an exact age_declaration)"
        )
    elif age < MIN_AGE:
        issues.append(f"age_under_18: declared age {age} is below 18")
    text = _plan_text(plan).lower()
    hits = sorted({term for term in MINOR_TERMS if term.lower() in text})
    for term in hits:
        issues.append(f"minor_indicator: plan text contains {term!r}")
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": not issues,
        "issues": issues,
        "declared_age": age,
        "minor_hits": hits,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    report = check_adult_portrait(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "adult_portrait.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "ok": report["ok"],
            "declared_age": report["declared_age"],
        },
    )


_Registered = False


def register_adult_portrait_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.adult_portrait_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Adult-portrait gate (hard intercept): the plan must "
                "declare an age of at least 18 and must contain no "
                "minor-indicating wording."
            ),
        )
    )
    return ["qa.adult_portrait_gate"]


register_adult_portrait_gate_capabilities_once()
