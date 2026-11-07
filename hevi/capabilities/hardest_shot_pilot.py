"""Hardest-shot pilot + quota reserve gate (``qa.hardest_shot_pilot``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 3 ("hardest shot first, quota held back"): do not start with
shot one. Pick the hardest shot -- big motion, a turn, a costume
change, complex camera work -- and run it as the pilot. If the
pilot passes, the constraints and prompt structure are sound and
the batch may proceed; if it fails, the problem surfaces early,
when rework is cheapest. And never spend the whole quota at once:
a caller-supplied fraction of the round's quota is held back for
fixes, so a batch that needs correction still has room to correct.

Difficulty is scored deterministically from four caller-declared
flags on each shot -- ``big_motion``, ``turn``, ``costume_change``,
``complex_camera`` -- one point each. The pilot must be a shot
with the highest score (ties go to the earliest shot). The flags
are declarations, not measurements: a shot that hides its hardest
move behind unflagged text is a planning failure this gate cannot
see, and the gate says so in its report instead of pretending
otherwise.

The reserve fraction is required caller input in (0, 1): no
number in this module defaults it from the article's example.
A pilot whose result is ``fail`` refuses the batch; a pilot whose
result is ``not_checked`` refuses it too -- untested is not
passed (see ``qa.verdict_vocabulary``). Quota arithmetic is exact:
``batch_units + reserve_units <= remaining_units`` where
``reserve_units = total_units * reserve_fraction`` and
``remaining_units = total_units - pilot_units``.

This module judges plans and pilot evidence only. It runs no
generation and spends nothing.
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

DIFFICULTY_FLAGS = (
    "big_motion",
    "turn",
    "costume_change",
    "complex_camera",
)

_EPS = 1e-9


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def difficulty_score(shot: dict[str, Any]) -> dict[str, Any]:
    """Score one shot's declared difficulty: one point per flag set."""
    flags = shot.get("difficulty") or {}
    if not isinstance(flags, dict):
        return {"score": 0, "flags": {},
                "issue": "difficulty must be an object of boolean flags"}
    scored: dict[str, bool] = {}
    for flag in DIFFICULTY_FLAGS:
        scored[flag] = flags.get(flag) is True
    unknown = sorted(set(flags) - set(DIFFICULTY_FLAGS))
    result: dict[str, Any] = {
        "score": sum(1 for v in scored.values() if v),
        "flags": scored,
    }
    if unknown:
        result["issue"] = (
            f"unknown difficulty flags ignored: {unknown}; the scored "
            f"flags are {', '.join(DIFFICULTY_FLAGS)}")
    return result


def select_pilot(shots: list[dict[str, Any]]) -> dict[str, Any]:
    """The hardest shot: highest score, earliest on ties."""
    scored = [(difficulty_score(s)["score"], i, s)
              for i, s in enumerate(shots)]
    best_score, best_index, best_shot = max(
        scored, key=lambda item: (item[0], -item[1]))
    return {"shot_id": best_shot.get("shot_id"),
            "shot_index": best_index,
            "difficulty_score": best_score,
            "flags": difficulty_score(best_shot)["flags"]}


def check_pilot_batch(
    shots: Any,
    *,
    pilot_shot_id: Any,
    pilot_result: Any,
    pilot_units: Any,
    total_units: Any,
    batch_units: Any,
    reserve_fraction: Any,
) -> dict[str, Any]:
    """Judge whether a batch may run after its pilot. Returns a report."""
    issues: list[dict[str, Any]] = []
    if not isinstance(shots, list) or not shots:
        issues.append({
            "code": "shots_missing",
            "detail": "qa.hardest_shot_pilot: shots must be a non-empty list",
        })
        return {"ok": False, "verdict": "fail", "issues": issues,
                "pilot": None, "quota": None}
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict) or not shot.get("shot_id"):
            issues.append({
                "code": "shot_without_id",
                "detail": f"qa.hardest_shot_pilot: shot {index} needs a "
                         "shot_id so the pilot can name it",
            })
    if issues:
        return {"ok": False, "verdict": "fail", "issues": issues,
                "pilot": None, "quota": None}

    pilot = select_pilot(shots)
    if pilot_shot_id != pilot["shot_id"]:
        issues.append({
            "code": "pilot_not_hardest",
            "detail": "qa.hardest_shot_pilot: pilot shot is "
                     f"{pilot_shot_id!r} but the hardest shot is "
                     f"{pilot['shot_id']!r} (difficulty "
                     f"{pilot['difficulty_score']}, flags "
                     f"{pilot['flags']}); run the hardest shot first, "
                     "not the easiest or the first in order",
        })
    if pilot_result not in ("pass", "fail", "not_checked"):
        issues.append({
            "code": "bad_pilot_result",
            "detail": "qa.hardest_shot_pilot: pilot_result must be pass, "
                     f"fail, or not_checked, not {pilot_result!r}",
        })
    elif pilot_result == "fail":
        issues.append({
            "code": "pilot_failed",
            "detail": "qa.hardest_shot_pilot: the pilot shot failed; the "
                     "batch is refused so the problem is fixed while "
                     "rework is cheapest",
        })
    elif pilot_result == "not_checked":
        issues.append({
            "code": "pilot_not_checked",
            "detail": "qa.hardest_shot_pilot: the pilot shot was not "
                     "checked; untested is not passed, so the batch "
                     "is refused",
        })

    quota: dict[str, Any] | None = None
    if not _is_number(reserve_fraction) \
            or not 0 < float(reserve_fraction) < 1:
        issues.append({
            "code": "bad_reserve_fraction",
            "detail": "qa.hardest_shot_pilot: reserve_fraction is required "
                     "and must be strictly between 0 and 1; it is set by "
                     "the caller, never defaulted from an article example",
        })
    elif not all(_is_int(v) and int(v) >= 0
                 for v in (pilot_units, total_units, batch_units)):
        issues.append({
            "code": "bad_quota_units",
            "detail": "qa.hardest_shot_pilot: pilot_units, total_units and "
                     "batch_units must be whole numbers of at least 0",
        })
    else:
        total = int(total_units)
        pilot_spent = int(pilot_units)
        batch = int(batch_units)
        reserve_units = total * float(reserve_fraction)
        remaining = total - pilot_spent
        quota = {
            "total_units": total,
            "pilot_units": pilot_spent,
            "batch_units": batch,
            "reserve_fraction": float(reserve_fraction),
            "reserve_units": reserve_units,
            "remaining_units": remaining,
        }
        if pilot_spent > total:
            issues.append({
                "code": "pilot_over_quota",
                "detail": "qa.hardest_shot_pilot: the pilot alone spent "
                         f"{pilot_spent} units of {total}",
            })
        elif batch + reserve_units > remaining + _EPS:
            issues.append({
                "code": "reserve_exhausted",
                "detail": "qa.hardest_shot_pilot: batch of "
                         f"{batch} units plus the held-back reserve "
                         f"({reserve_units} units) exceeds the "
                         f"{remaining} units left after the pilot; "
                         "shrink the batch or raise the quota so fixes "
                         "still have room",
            })

    ok = not issues
    return {"ok": ok, "verdict": "pass" if ok else "fail",
            "issues": issues,
            "pilot": {**pilot, "pilot_shot_id": pilot_shot_id,
                      "pilot_result": pilot_result},
            "quota": quota}


def authorize_pilot_batch(
    shots: Any,
    *,
    pilot_shot_id: Any,
    pilot_result: Any,
    pilot_units: Any,
    total_units: Any,
    batch_units: Any,
    reserve_fraction: Any,
) -> dict[str, Any]:
    """Approve a post-pilot batch, or refuse it loudly (raises CapabilityError)."""
    report = check_pilot_batch(
        shots, pilot_shot_id=pilot_shot_id, pilot_result=pilot_result,
        pilot_units=pilot_units, total_units=total_units,
        batch_units=batch_units, reserve_fraction=reserve_fraction)
    if not report["ok"]:
        raise CapabilityError(
            "qa.hardest_shot_pilot: batch refused: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = authorize_pilot_batch(
        params.get("shots"),
        pilot_shot_id=params.get("pilot_shot_id"),
        pilot_result=params.get("pilot_result"),
        pilot_units=params.get("pilot_units"),
        total_units=params.get("total_units"),
        batch_units=params.get("batch_units"),
        reserve_fraction=params.get("reserve_fraction"))
    report_path = out_dir / "hardest_shot_pilot.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_hardest_shot_pilot_capabilities_once() -> list[str]:
    """Register ``qa.hardest_shot_pilot`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.hardest_shot_pilot",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "shots": {"type": "array"},
                    "pilot_shot_id": {"type": "string"},
                    "pilot_result": {"type": "string"},
                    "pilot_units": {"type": "integer", "minimum": 0},
                    "total_units": {"type": "integer", "minimum": 0},
                    "batch_units": {"type": "integer", "minimum": 0},
                    "reserve_fraction": {"type": "number"},
                },
                "required": ["shots", "pilot_shot_id", "pilot_result",
                             "pilot_units", "total_units", "batch_units",
                             "reserve_fraction"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Hardest-shot pilot gate: the pilot must be the "
                "highest-difficulty shot (big motion / turn / costume "
                "change / complex camera flags), a failed or untested "
                "pilot refuses the batch, and a caller-supplied "
                "fraction of the quota stays held back for fixes. "
                "Judges plans and pilot evidence only; runs no "
                "generation."
            ),
            line="qa",
        )
    )
    return ["qa.hardest_shot_pilot"]


register_hardest_shot_pilot_capabilities_once()
