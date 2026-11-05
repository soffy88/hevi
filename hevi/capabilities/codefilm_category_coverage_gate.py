"""Code-film category coverage gate (``qa.codefilm_category_coverage_gate``).

Clean-room restatement of the category discipline recorded in the
Infinite Creation delta2 review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a code-film style index is
only as honest as its category coverage. This gate judges a
caller-supplied index: style ids must be unique slugs, every
category must come from the closed eleven-family list, and a
claim to match the reviewed 66-style shape must reproduce the
reviewed per-category breakdown exactly. A claim that every
style was individually rendered is never accepted here: no
rendering happens in this gate, and per-style rendering stays
unverified until a real rendering run checks it.

The eleven category labels below are the house's own short
labels, the same closed list used by
``video.code_film_style_contract``. The 66 total and its
breakdown are the reviewed project's numbers, recorded as
unverified claims about an external library: this gate only
checks that a caller-supplied index is internally consistent
with the shape it claims.
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

_Registered = False

CATEGORIES = (
    "editing_documentary",
    "evidence_imaging",
    "hand_drawn",
    "east_asian_traditional",
    "print",
    "graphic_typography",
    "information_publishing",
    "cartoon_animation",
    "game",
    "film_era",
    "material_3d",
)

# Per-category counts recorded in the delta2 review for the
# reviewed 66-style shape. Used only when a caller claims that
# exact shape (claimed_total == 66); never asserted about any
# external library by this module.
REVIEWED_BREAKDOWN: dict[str, int] = {
    "editing_documentary": 8,
    "evidence_imaging": 8,
    "hand_drawn": 8,
    "east_asian_traditional": 4,
    "print": 6,
    "graphic_typography": 7,
    "information_publishing": 8,
    "cartoon_animation": 4,
    "game": 4,
    "film_era": 2,
    "material_3d": 7,
}
REVIEWED_TOTAL = 66

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.codefilm_category_coverage_gate: {detail}"}
    issue.update(extra)
    return issue


def check_codefilm_category_coverage(index: Any) -> dict[str, Any]:
    """Judge one caller-supplied code-film style index.

    ``index`` carries ``styles`` (each with ``id``, ``category``
    and ``folder``), an optional ``claimed_total``, and an
    optional ``render_verification`` record. Verdict ``pass``
    means ids are unique slugs, categories are closed, folders
    are declared, a claimed total matches the counted total, a
    claimed 66-style shape reproduces the reviewed breakdown,
    and no per-style rendering is claimed as verified.
    """
    if not isinstance(index, dict):
        raise CapabilityError("style index must be an object")
    issues: list[dict[str, Any]] = []
    styles = index.get("styles")
    if not isinstance(styles, list) or not styles:
        raise CapabilityError("style index requires a non-empty styles list")
    seen_ids: set[str] = set()
    per_category: dict[str, int] = {}
    for position, style in enumerate(styles):
        if not isinstance(style, dict):
            issues.append(_issue("style_not_object", f"style {position} is not an object"))
            continue
        style_id = style.get("id")
        if not isinstance(style_id, str) or not _SLUG_RE.match(style_id):
            issues.append(
                _issue("style_id_invalid", f"style {position} id must be a lowercase slug")
            )
            continue
        if style_id in seen_ids:
            issues.append(_issue("style_id_duplicate", f"style id {style_id} is duplicated"))
        seen_ids.add(style_id)
        category = style.get("category")
        if category not in CATEGORIES:
            issues.append(
                _issue(
                    "category_invalid",
                    f"style {style_id} category must be one of the closed list",
                    style=style_id,
                )
            )
        else:
            per_category[category] = per_category.get(category, 0) + 1
        if not isinstance(style.get("folder"), str) or not style["folder"].strip():
            issues.append(
                _issue("folder_missing", f"style {style_id} lacks a folder", style=style_id)
            )
    counted = len(seen_ids)
    claimed_total = index.get("claimed_total")
    if claimed_total is not None:
        if not isinstance(claimed_total, int) or claimed_total <= 0:
            issues.append(
                _issue("claimed_total_invalid", "claimed_total must be a positive integer")
            )
        elif claimed_total != counted:
            issues.append(
                _issue(
                    "claimed_total_mismatch",
                    f"claimed_total {claimed_total} does not match counted total {counted}",
                )
            )
        elif claimed_total == REVIEWED_TOTAL:
            for category, expected in REVIEWED_BREAKDOWN.items():
                if per_category.get(category, 0) != expected:
                    issues.append(
                        _issue(
                            "breakdown_mismatch",
                            f"category {category} has {per_category.get(category, 0)} styles, "
                            f"reviewed breakdown requires {expected}",
                            category=category,
                        )
                    )
    verification = index.get("render_verification")
    if verification is not None:
        if not isinstance(verification, dict):
            issues.append(
                _issue("render_verification_invalid", "render_verification must be an object")
            )
        elif verification.get("per_style_rendered") is True:
            issues.append(
                _issue(
                    "unverified_render_claim",
                    "per-style rendering is unverified by this gate; a claim that "
                    "every style was individually rendered requires a real rendering run",
                )
            )
    missing_categories = [category for category in CATEGORIES if category not in per_category]
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": ["per-style rendering is unverified by this gate"],
        "style_count": counted,
        "per_category": per_category,
        "missing_categories": missing_categories,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_codefilm_category_coverage(params.get("index"))
    report_path = out_dir / "codefilm_category_coverage.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_codefilm_category_coverage_gate_capabilities_once() -> list[str]:
    """Register ``qa.codefilm_category_coverage_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.codefilm_category_coverage_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "index": {"type": "object"},
                },
                "required": ["index"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Code-film category coverage gate: a style index must use "
                "unique slug ids and the closed eleven-category list, a "
                "claimed total must match the counted total, a claimed "
                "66-style shape must reproduce the reviewed breakdown, and "
                "no per-style rendering may be claimed as verified."
            ),
        )
    )
    return ["qa.codefilm_category_coverage_gate"]


__all__ = [
    "CATEGORIES",
    "REVIEWED_BREAKDOWN",
    "REVIEWED_TOTAL",
    "check_codefilm_category_coverage",
    "register_codefilm_category_coverage_gate_capabilities_once",
]
