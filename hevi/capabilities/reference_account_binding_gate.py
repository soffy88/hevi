"""Reference account-binding gate (``qa.reference_account_binding_gate``).

Clean-room rewrite of the discipline in ``hevi-vs-digital-human-koubo-recheck.md``
item A5: an image reference used to fix a presenter's likeness
must declare which account it is bound to. A reference is bound
either to the caller themselves or to a named authoriser with a
stated scope; a reference with no binding declaration fails, and
a reference that reuses material across accounts fails.

Hard exclusions, stated so a caller cannot miss them:

* Material belonging to someone else without authorisation fails,
  including any record that admits unlicensed third-party material.
* Demonstration identities, author persona identifiers, and
  author material identifiers must never be written into a
  reference record or a default. A record carrying any of
  ``demo_identity``, ``persona_id`` or ``material_id`` fails.
* No default reference is supplied here at all: the caller must
  declare every reference explicitly.

This module judges declarations only. It never reads an image,
never stores a likeness, and never contacts any account.
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

_Registered = False

# Fields that must never appear with a value in a reference record:
# demonstration identities and author-side persona/material ids.
_FORBIDDEN_FIELDS = ("demo_identity", "persona_id", "material_id")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.reference_account_binding_gate: {detail}"}
    issue.update(extra)
    return issue


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_reference_account_binding(record: Any) -> dict[str, Any]:
    """Judge one reference declaration. Returns a report; never raises."""
    issues: list[dict[str, Any]] = []
    if not isinstance(record, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("record_not_object", "reference record must be an object")],
        }
    if not _non_empty(record.get("reference_id")):
        issues.append(_issue(
            "reference_id_missing",
            "the reference must carry a non-empty reference_id",
        ))
    if not _non_empty(record.get("source_account")):
        issues.append(_issue(
            "source_account_missing",
            "the reference must name the account it belongs to "
            "(source_account); a reference without an account binding "
            "cannot be used",
        ))
    for field in _FORBIDDEN_FIELDS:
        if record.get(field):
            issues.append(_issue(
                "forbidden_identity_field",
                f"field {field!r} must never appear in a reference "
                "record: demonstration identities and author "
                "persona/material ids are not reusable references",
                field=field,
            ))
    binding = record.get("account_binding")
    if not isinstance(binding, dict):
        issues.append(_issue(
            "account_binding_missing",
            "the reference must declare its account binding: kind "
            "'self' or 'authorised', with authoriser and scope for "
            "authorised material",
        ))
    else:
        kind = binding.get("kind")
        if kind == "self":
            if not _non_empty(binding.get("owner")):
                issues.append(_issue(
                    "binding_owner_missing",
                    "a 'self' binding must name its owner",
                ))
        elif kind == "authorised":
            if not _non_empty(binding.get("authoriser")):
                issues.append(_issue(
                    "binding_authoriser_missing",
                    "an 'authorised' binding must name the authoriser",
                ))
            if not _non_empty(binding.get("scope")):
                issues.append(_issue(
                    "binding_scope_missing",
                    "an 'authorised' binding must state the authorised scope",
                ))
        else:
            issues.append(_issue(
                "binding_kind_invalid",
                "account_binding kind must be 'self' or 'authorised'",
            ))
    if record.get("contains_unlicensed_third_party_material") is True:
        issues.append(_issue(
            "unlicensed_third_party_material",
            "the reference admits unlicensed third-party material; "
            "it must not be used",
        ))
    if record.get("cross_account_reuse") is True:
        issues.append(_issue(
            "cross_account_reuse",
            "a reference bound to one account must not be reused "
            "under another account",
        ))
    return {
        "ok": not issues,
        "verdict": "pass" if not issues else "fail",
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_reference_account_binding(params.get("record"))
    report_path = Path(out_dir) / "reference_account_binding_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_reference_account_binding_gate_capabilities_once() -> list[str]:
    """Register ``qa.reference_account_binding_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.reference_account_binding_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                },
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Reference account-binding gate: an image reference "
                "must declare its account binding (self or named "
                "authoriser with scope); unlicensed third-party "
                "material, cross-account reuse, and demonstration / "
                "author persona / material ids are refused. Judges "
                "declarations only."
            ),
            line="qa",
        )
    )
    return ["qa.reference_account_binding_gate"]


register_reference_account_binding_gate_capabilities_once()
