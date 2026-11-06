"""Film ledger difference gate (``qa.film_ledger_difference_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): a new film
must not repeat what was already delivered. Against every
delivered film, the new film must differ in at least four of
the six axes — opening, structure, signature move, palette,
sound, ending. A new film that is too close to any delivered
film fails. This gate judges the ledger record only. It
renders nothing: ``executed_here`` is always false.
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

# The six axes a new film is compared on.
DIFFERENCE_AXES: tuple[str, ...] = (
    "opening",
    "structure",
    "signature_move",
    "palette",
    "sound",
    "ending",
)
MIN_DIFFERENCES = 4


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_film_ledger_difference(ledger: Any) -> dict[str, Any]:
    """Validate a new film against the delivered-film ledger.

    Pass requires the new film to state all six axes and to
    differ from every delivered film in at least four of
    them.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(ledger, dict):
        return fail("ledger_not_object", "ledger must be a JSON object")
    new_film = ledger.get("new_film")
    if not isinstance(new_film, dict):
        return fail(
            "new_film_missing",
            "ledger must state the new film",
        )
    for axis in DIFFERENCE_AXES:
        if not new_film.get(axis):
            return fail(
                "axes_missing",
                f"new film is missing the {axis} axis; all six axes must be stated",
            )
    delivered = ledger.get("delivered_films")
    if not isinstance(delivered, list):
        return fail(
            "delivered_films_missing",
            "ledger must list the delivered films",
        )
    differences = ledger.get("differences")
    if not isinstance(differences, dict):
        return fail(
            "differences_missing",
            "ledger must state, per delivered film, which axes differ",
        )
    for film in delivered:
        if not isinstance(film, str):
            return fail(
                "delivered_film_not_id",
                "every delivered film must be named by its id",
            )
        axes = differences.get(film)
        if not isinstance(axes, list):
            return fail(
                "differences_missing",
                f"ledger states no differing axes against delivered film {film}",
            )
        unknown = [axis for axis in axes if axis not in DIFFERENCE_AXES]
        if unknown:
            return fail(
                "difference_axis_unknown",
                f"differences against {film} name unknown axes: {', '.join(unknown)}",
            )
        if len(set(axes)) < MIN_DIFFERENCES:
            return fail(
                "too_similar",
                f"new film differs from delivered film {film} in only "
                f"{len(set(axes))} of 6 axes; at least 4 are required",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_film_ledger_difference(params.get("ledger"))
    report_path = out_dir / "film_ledger_difference_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_film_ledger_difference_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.film_ledger_difference_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "ledger": {"type": "object"},
                },
                "required": ["ledger"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Film ledger difference gate: a new film must differ "
                "from every delivered film in at least 4 of 6 axes "
                "(opening, structure, signature move, palette, sound, "
                "ending)."
            ),
        )
    )
    return ["qa.film_ledger_difference_gate"]


__all__ = [
    "DIFFERENCE_AXES",
    "MIN_DIFFERENCES",
    "check_film_ledger_difference",
    "register_film_ledger_difference_gate_capabilities_once",
]
