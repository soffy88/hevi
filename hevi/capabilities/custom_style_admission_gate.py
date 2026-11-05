"""Custom style admission gate (``qa.custom_style_admission_gate``).

Clean-room restatement of the custom-style discipline recorded
in the Infinite Creation delta2 review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a style library may hold
built-in styles and caller-defined custom styles, but the two
must never be confused. A custom style is admitted only when it
declares the built-in style it starts from, the fields it
overrides, and where it came from; it must never claim to be
one of the built-in set. A built-in claim needs a named index
to belong to. This gate judges admission records only: it
carries no style code, no style prose, and no artwork.
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
    issue = {"code": code, "detail": f"qa.custom_style_admission_gate: {detail}"}
    issue.update(extra)
    return issue


def check_custom_style_admission(style: Any, builtin_ids: Any = None) -> dict[str, Any]:
    """Judge one style admission record.

    ``style`` carries ``id``, ``category`` and ``is_custom``. A
    custom style must also carry ``base_declaration`` (with
    ``base_id`` and a non-empty ``overridden_fields`` list) and a
    non-empty ``source``. A claim to be built-in (``claims_builtin``)
    fails for a custom style, and needs a named ``builtin_index``
    otherwise. When ``builtin_ids`` is supplied, a custom id that
    collides with a built-in id fails as impersonation.
    """
    if not isinstance(style, dict):
        raise CapabilityError("style admission record must be an object")
    if builtin_ids is not None and not isinstance(builtin_ids, list):
        raise CapabilityError("builtin_ids must be a list when supplied")
    issues: list[dict[str, Any]] = []
    style_id = style.get("id")
    if not isinstance(style_id, str) or not _SLUG_RE.match(style_id):
        issues.append(_issue("style_id_invalid", "style id must be a lowercase slug"))
        style_id = None
    if style.get("category") not in CATEGORIES:
        issues.append(_issue("category_invalid", "style category must be one of the closed list"))
    is_custom = style.get("is_custom")
    if not isinstance(is_custom, bool):
        issues.append(_issue("is_custom_missing", "style must declare is_custom as a boolean"))
        is_custom = False
    if is_custom:
        if builtin_ids is not None and style_id in builtin_ids:
            issues.append(
                _issue(
                    "builtin_id_collision",
                    f"custom style id {style_id} collides with a built-in id",
                    style=style_id,
                )
            )
        base = style.get("base_declaration")
        if not isinstance(base, dict):
            issues.append(
                _issue("base_declaration_missing", "custom style requires a base_declaration")
            )
        else:
            base_id = base.get("base_id")
            if not isinstance(base_id, str) or not _SLUG_RE.match(base_id):
                issues.append(
                    _issue("base_id_invalid", "base_declaration.base_id must be a lowercase slug")
                )
            elif style_id is not None and base_id == style_id:
                issues.append(
                    _issue("base_id_self", "custom style base_id must differ from its own id")
                )
            overridden = base.get("overridden_fields")
            if not isinstance(overridden, list) or not overridden:
                issues.append(
                    _issue(
                        "overridden_fields_missing",
                        "base_declaration requires a non-empty overridden_fields list",
                    )
                )
            elif not all(isinstance(field, str) and field.strip() for field in overridden):
                issues.append(
                    _issue(
                        "overridden_fields_invalid",
                        "overridden_fields entries must be non-empty strings",
                    )
                )
        if not isinstance(style.get("source"), str) or not style["source"].strip():
            issues.append(_issue("source_missing", "custom style requires a non-empty source"))
        if style.get("claims_builtin") is True:
            issues.append(
                _issue(
                    "builtin_claim",
                    "a custom style must never claim to be one of the built-in set",
                    style=style_id,
                )
            )
    else:
        if style.get("claims_builtin") is True and (
            not isinstance(style.get("builtin_index"), str) or not style["builtin_index"].strip()
        ):
            issues.append(
                _issue(
                    "builtin_index_missing",
                    "a built-in claim requires a named builtin_index",
                    style=style_id,
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": ["whether the style renders as described is unverified by this gate"],
        "style_id": style.get("id"),
        "is_custom": is_custom,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_custom_style_admission(params.get("style"), params.get("builtin_ids"))
    report_path = out_dir / "custom_style_admission.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_custom_style_admission_gate_capabilities_once() -> list[str]:
    """Register ``qa.custom_style_admission_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.custom_style_admission_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "style": {"type": "object"},
                    "builtin_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["style"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Custom style admission gate: a custom style must declare "
                "its base style, overridden fields and source, and must "
                "never claim built-in membership; a built-in claim needs "
                "a named index."
            ),
        )
    )
    return ["qa.custom_style_admission_gate"]


__all__ = [
    "check_custom_style_admission",
    "register_custom_style_admission_gate_capabilities_once",
]
