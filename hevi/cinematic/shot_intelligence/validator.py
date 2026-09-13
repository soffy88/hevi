"""Static visual QA for shot plans; warnings never alter qualification gates."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.cinematic.shot_intelligence.models import ShotPlan


@dataclass(frozen=True)
class VisualQAResult:
    status: str
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


def validate_shot_plan(plan: ShotPlan) -> VisualQAResult:
    warnings: list[str] = list(plan.diagnostics)
    failures: list[str] = []
    for shot in plan.shots:
        if not shot.id or not shot.framing or not shot.shot_type:
            failures.append("underspecified_shot")
        if shot.duration_range_s[1] > 12:
            warnings.append("excessive_duration")
        if not shot.provenance:
            failures.append(f"missing_provenance:{shot.id}")
    if plan.shots and not any("wide" in shot.tags or shot.shot_type == "establishing" for shot in plan.shots):
        warnings.append("missing_establishing_context")
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return VisualQAResult(status, tuple(dict.fromkeys(warnings)), tuple(dict.fromkeys(failures)))

