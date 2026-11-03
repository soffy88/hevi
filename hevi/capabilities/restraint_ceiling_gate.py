"""Restraint-ceiling gate (``qa.restraint_ceiling_gate``).

This gate reuses the existing conflict machinery -- it invents no
second doctrine.  Three checks, all grounded in
``hevi/image/portrait_vocab/PHRASING.md`` and
``hevi/image/portrait_vocab/assemble.py``:

1. Conflicts (PHRASING rule 4, "conflicting items take one of
   two"): every conflict reported by ``find_conflicts`` over the
   plan's existing-index picks fails, with the assembler's own
   reason carried through.
2. Exaggeration (PHRASING rule 10, amplitude kept restrained):
   unquantified exaggeration terms in the prompt text fail.
3. Synonym stacking (PHRASING rule 5, "keep one synonymous
   adjective"): three or more distinct synonyms from one closed
   group in the Chinese text fail.  The threshold is three, not
   two, because two near-synonyms may legitimately modify
   different targets (light and expression); three in one group
   is stacking by any reading.

Shape: ``{"picks": {category: entry}, "text": "...",
"text_en": "..."}``.  ``picks`` uses the existing 66-entry index
(an entry id, Chinese name, or English phrase per category).
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

EXAGGERATION_TERMS: frozenset[str] = frozenset(
    {
        "夸张",
        "过度浓妆",
        "浓妆艳抹",
        "极致",
        "惊艳",
        "exaggerated",
        "heavy makeup",
        "oversized",
        "caricature",
    }
)

# Closed synonym groups for the stacking check (Chinese text only;
# bilingual repetition across zh/en is not stacking).
SYNONYM_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"柔和", "温柔", "温暖", "亲切"}),
    frozenset({"优雅", "高贵", "端庄", "典雅"}),
    frozenset({"自然", "真实", "生动", "逼真"}),
)

STACK_THRESHOLD = 3


def _resolve_picks(picks: Any) -> list[dict[str, Any]]:
    from hevi.image.portrait_vocab import vocab as pv

    if not isinstance(picks, dict):
        raise CapabilityError("restraint plan.picks must be an object")
    resolved: list[dict[str, Any]] = []
    for category, raw in picks.items():
        if raw is None or not str(raw).strip():
            continue
        entry = pv.get_entry(raw)
        if entry["category"] != category:
            raise CapabilityError(
                f"pick {raw!r} belongs to category {entry['category']!r}, "
                f"not {category!r}"
            )
        resolved.append(entry)
    return resolved


def check_restraint_ceiling(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Judge conflicts, exaggeration, and synonym stacking."""
    from hevi.image.portrait_vocab.assemble import find_conflicts

    if not isinstance(plan, dict):
        raise CapabilityError("restraint plan must be an object")
    issues: list[str] = []
    resolved = _resolve_picks(plan.get("picks", {}))
    for conflict in find_conflicts(resolved):
        issues.append(
            f"conflict: {conflict['a']} x {conflict['b']}: {conflict['reason']}"
        )
    text_zh = str(plan.get("text", ""))
    text_en = str(plan.get("text_en", ""))
    lowered_en = text_en.lower()
    for term in EXAGGERATION_TERMS:
        if term in text_zh or term.lower() in lowered_en:
            issues.append(f"exaggeration: prompt text contains {term!r}")
    for group in SYNONYM_GROUPS:
        hits = sorted({term for term in group if term in text_zh})
        if len(hits) >= STACK_THRESHOLD:
            issues.append(
                "synonym_stack: Chinese text stacks "
                f"{len(hits)} synonyms from one group: {', '.join(hits)}"
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": not issues,
        "issues": issues,
        "conflicts": find_conflicts(resolved),
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    report = check_restraint_ceiling(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "restraint_ceiling.json"
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
        },
    )


_Registered = False


def register_restraint_ceiling_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.restraint_ceiling_gate",
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
                "Restraint-ceiling gate: reuses the portrait "
                "assembler's conflict detection plus exaggeration and "
                "synonym-stacking checks from the phrasing spec."
            ),
        )
    )
    return ["qa.restraint_ceiling_gate"]


register_restraint_ceiling_gate_capabilities_once()
