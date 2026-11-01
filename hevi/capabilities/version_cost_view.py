"""Per-version cost view (``qa.version_cost_view``).

Clean-room rewrite of the method in ``hevi-vs-rain-before-stops.md``
item A5 (from the ``<雨停之前>`` field notes): a project's spend
is read version by version -- V1, V2, ... -- each with its
shooting method and a note when the version's cost is mostly
tuition (trial and error). The view is read-only: it never writes
the ledger and never changes the ``spend_ledger`` / ``spend_brake``
calibre. Two refusals are load-bearing:

1. Versions shot with different methods (e.g. 1080p shot-by-shot
   vs 480p by scene) are marked ``comparable: false`` -- their
   totals must not be divided into a "savings multiple".
2. A version total that includes trial-and-error tuition must be
   labelled as such, and the view never emits a per-episode quote:
   one project's tuition-heavy ledger is not a price. A caller
   asking for ``quote_per_episode`` gets ``quote_refused``.

Ledger batches are read through ``spend_ledger.ledger_summary``
shapes: this view accepts a ledger document (the JSON the ledger
module saves) and a version map supplied by the caller. It
invents no price: batch totals come from the ledger document
itself.

This module reads records only. It never generates, never calls a
model, never spends.
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

# The field-note ledger this view was designed against: the
# "about 3,500 yuan" total is tuition-heavy (one 1080p round took
# ~73% of the video spend) and excludes subscription and labour.
# These strings are labels the view requires on tuition-heavy
# totals; they are not prices and not defaults.
REQUIRED_TUITION_NOTE = "includes trial-and-error tuition; excludes subscription and labour"


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.version_cost_view: {detail}"}
    issue.update(extra)
    return issue


def _round(value: float) -> float:
    return round(float(value), 2)


def build_version_cost_view(ledger: Any, versions: Any,
                            request_quote: bool = False) -> dict[str, Any]:
    """Build a read-only per-version cost view. Never raises for bad input."""
    issues: list[dict[str, Any]] = []
    if request_quote:
        issues.append(_issue(
            "quote_refused",
            "this view never emits a per-episode quote: one project's "
            "tuition-heavy ledger is not a price",
        ))
    if not isinstance(ledger, dict) or not isinstance(ledger.get("batches"), list):
        return {
            "ok": False,
            "versions": [],
            "issues": [_issue(
                "ledger_invalid", "ledger must be an object with a batches list",
            )],
        }
    if not isinstance(versions, list) or not versions:
        return {
            "ok": False,
            "versions": [],
            "issues": [_issue(
                "versions_missing", "versions must be a non-empty list",
            )],
        }
    batches = {
        batch["batch_id"]: batch
        for batch in ledger["batches"]
        if isinstance(batch, dict) and isinstance(batch.get("batch_id"), str)
    }
    methods: set[str] = set()
    view_versions: list[dict[str, Any]] = []
    for version in versions:
        if not isinstance(version, dict):
            issues.append(_issue("version_not_object", "each version must be an object"))
            continue
        version_id = version.get("version_id")
        batch_ids = version.get("batch_ids")
        method = version.get("method")
        if not isinstance(version_id, str) or not version_id.strip():
            issues.append(_issue("version_id_missing", "each version needs a version_id"))
            continue
        if not isinstance(batch_ids, list) or not batch_ids:
            issues.append(_issue(
                "version_batches_missing",
                f"version {version_id!r} must list its ledger batch_ids",
                version_id=version_id,
            ))
            continue
        if not isinstance(method, str) or not method.strip():
            issues.append(_issue(
                "version_method_missing",
                f"version {version_id!r} must state its shooting method",
                version_id=version_id,
            ))
            continue
        methods.add(method)
        estimated = 0.0
        actual = 0.0
        missing = []
        for batch_id in batch_ids:
            batch = batches.get(batch_id)
            if batch is None:
                missing.append(batch_id)
                continue
            estimated += float(batch.get("estimated_total") or 0.0)
            if batch.get("actual_total") is not None:
                actual += float(batch["actual_total"])
        if missing:
            issues.append(_issue(
                "version_batch_missing",
                f"version {version_id!r} references unknown batch_ids: {missing}",
                version_id=version_id,
                batch_ids=missing,
            ))
        tuition = version.get("trial_and_error") is True
        note = version.get("cost_basis_note")
        if tuition and note != REQUIRED_TUITION_NOTE:
            issues.append(_issue(
                "tuition_note_missing",
                f"version {version_id!r} is trial-and-error tuition and must carry "
                f"cost_basis_note {REQUIRED_TUITION_NOTE!r}",
                version_id=version_id,
            ))
        view_versions.append({
            "version_id": version_id,
            "method": method,
            "trial_and_error": tuition,
            "estimated_total": _round(estimated),
            "actual_total": _round(actual) if actual else None,
            "cost_basis_note": note,
        })
    comparable = len(methods) <= 1
    return {
        "ok": not issues,
        "comparable": comparable,
        "comparability_note": (
            "all versions share one shooting method"
            if comparable
            else "methods differ across versions; totals must not be divided into a savings multiple"
        ),
        "versions": view_versions,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = build_version_cost_view(
        params.get("ledger"), params.get("versions"),
        request_quote=bool(params.get("request_quote", False)),
    )
    report_path = Path(out_dir) / "version_cost_view.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "verdict": "pass" if report["ok"] else "fail"},
    )


def register_version_cost_view_capabilities_once() -> list[str]:
    """Register ``qa.version_cost_view`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.version_cost_view",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "ledger": {"type": "object"},
                    "versions": {"type": "array"},
                    "request_quote": {"type": "boolean"},
                },
                "required": ["ledger", "versions"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Per-version cost view: read-only summary of a spend "
                "ledger by version, with shooting method and "
                "trial-and-error tuition labelled; different methods "
                "are marked incomparable and no per-episode quote is "
                "ever emitted. Reads records only."
            ),
            line="qa",
        )
    )
    return ["qa.version_cost_view"]


register_version_cost_view_capabilities_once()
