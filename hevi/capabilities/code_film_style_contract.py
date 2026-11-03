"""Code-film style contract (``video.code_film_style_contract``).

Schema-only contract for a code-rendered film style index, in
the spirit of the style library described in the Infinite
Creation review (see ``INFINITE_CREATION_ATTRIBUTION.md``).
This module holds metadata shapes only: style ids, categories,
folders, and render contracts. It carries no style code, no
style prose, no artwork, and no footage, and it renders
nothing: a frame record it checks must declare itself
unrendered here, and any record claiming a render without
evidence fails. Whether a style looks right on screen is a
question for a real rendering run, which is a separate case.

Category names below are the house's own short labels for the
eleven families the review counted. The count itself (66
styles) is the reviewed project's claim, recorded as
unverified here: this module never asserts how many styles any
external library holds, only that a caller-supplied index is
internally consistent.
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
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"video.code_film_style_contract: {detail}"}
    issue.update(extra)
    return issue


def validate_style_index(index: Any) -> dict[str, Any]:
    """Judge one style index for internal consistency.

    ``index`` carries ``styles`` (each with ``id``, ``category``,
    ``folder`` and a ``render_contract`` with ``browser_render``
    and ``webgl_required`` booleans). Verdict ``pass`` means ids
    are unique slugs, every category is in the closed list, and
    every style declares a render contract. No style content is
    judged, because none is present here.
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
            issues.append(_issue("style_id_invalid", f"style {position} id must be a lowercase slug"))
            continue
        if style_id in seen_ids:
            issues.append(_issue("style_id_duplicate", f"style id {style_id} is duplicated"))
        seen_ids.add(style_id)
        category = style.get("category")
        if category not in CATEGORIES:
            issues.append(
                _issue("category_invalid", f"style {style_id} category must be one of the closed list", style=style_id)
            )
        else:
            per_category[category] = per_category.get(category, 0) + 1
        if not isinstance(style.get("folder"), str) or not style["folder"].strip():
            issues.append(_issue("folder_missing", f"style {style_id} lacks a folder", style=style_id))
        contract = style.get("render_contract")
        if not isinstance(contract, dict):
            issues.append(_issue("render_contract_missing", f"style {style_id} lacks a render_contract", style=style_id))
            continue
        for field in ("browser_render", "webgl_required"):
            if not isinstance(contract.get(field), bool):
                issues.append(
                    _issue(
                        "render_contract_field",
                        f"style {style_id} render_contract.{field} must be a boolean",
                        style=style_id,
                    )
                )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "style_count": len(seen_ids),
        "per_category": per_category,
    }


def check_style_frame_record(index: Any, record: Any) -> dict[str, Any]:
    """Judge one caller-supplied frame record against the index.

    The record must name a style in the index, declare its frame
    geometry, and declare ``rendered_here`` false: this contract
    never renders. A record claiming a render without evidence
    fails as an unverified claim.
    """
    validation = validate_style_index(index)
    if validation["verdict"] == "fail":
        raise CapabilityError("style index failed validation; frame record cannot be judged")
    if not isinstance(record, dict):
        raise CapabilityError("frame record must be an object")
    issues: list[dict[str, Any]] = []
    styles = {style["id"]: style for style in index["styles"] if isinstance(style, dict)}
    style = styles.get(record.get("style_id"))
    if style is None:
        issues.append(_issue("style_unknown", f"frame record names unknown style {record.get('style_id')}"))
        return {
            "ok": False,
            "verdict": "fail",
            "issues": issues,
            "not_checked": [],
            "style_id": record.get("style_id"),
        }
    for field in ("width", "height", "frame_count", "fps"):
        value = record.get(field)
        if not isinstance(value, (int, float)) or value <= 0:
            issues.append(_issue("geometry_invalid", f"frame record {field} must be > 0", style=record.get("style_id")))
    if record.get("rendered_here") is not False:
        issues.append(
            _issue(
                "unverified_render_claim",
                "frame record must declare rendered_here false; this contract never renders",
                style=record.get("style_id"),
            )
        )
    contract = style.get("render_contract", {})
    if contract.get("webgl_required") and record.get("webgl_used") is not True:
        issues.append(
            _issue(
                "webgl_declaration_missing",
                f"style {record.get('style_id')} requires WebGL; record must declare webgl_used",
                style=record.get("style_id"),
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "style_id": record.get("style_id"),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = params.get("index")
    record = params.get("frame_record")
    if record is not None:
        report: dict[str, Any] = check_style_frame_record(index, record)
    else:
        report = validate_style_index(index)
    report_path = out_dir / "code_film_style_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_code_film_style_contract_capabilities_once() -> list[str]:
    """Register ``video.code_film_style_contract`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.code_film_style_contract",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "index": {"type": "object"},
                    "frame_record": {"type": "object"},
                },
                "required": ["index"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Code-film style contract (schema only): a style index must "
                "be internally consistent across a closed category list, and "
                "frame records must declare themselves unrendered here; no "
                "style code, prose, or footage is carried and nothing renders."
            ),
        )
    )
    return ["video.code_film_style_contract"]


__all__ = [
    "check_style_frame_record",
    "validate_style_index",
    "register_code_film_style_contract_capabilities_once",
]
