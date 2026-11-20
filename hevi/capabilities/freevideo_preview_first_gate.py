"""Preview-first + two-pass sampling gate (``qa.freevideo_preview_first_gate``).

Two-pass sampling runs a half-resolution first pass and
only completes the takes worth finishing; the second pass
reuses the first pass instead of redoing it. In the
reviewer's own words, a run fails when the first pass is
not half-resolution, when the second pass does not reuse
the first pass, when the first shot was not generated in
two seeds and reviewed at full size before continuing, or
when takes other than the liked ones are completed. The
gate judges run descriptions only; it never renders.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here.
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

FIRST_PASS_RESOLUTION_FRACTION = 0.5


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_freevideo_preview_first(run: Any) -> dict[str, Any]:
    """Validate a FreeVideo-style preview-first run.

    Verdicts are ``pass`` / ``fail`` only. A run fails when
    a required field is missing, when the first pass is not
    half-resolution or not completed, when a completed second
    pass does not reuse the first pass, when the first shot
    was not generated in two seeds, when the preview was not
    reviewed at full size before continuing, or when takes
    other than the liked ones are completed.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(run, dict):
        return fail("run_not_object", "preview-first run must be a JSON object")
    for field in (
        "first_pass",
        "second_pass",
        "preview_reviewed_full_size",
        "two_seeds_first_shot",
        "only_liked_completed",
    ):
        if field not in run:
            return fail("run_field_missing", f"preview-first run must carry {field!r}")
    first = run["first_pass"]
    if not isinstance(first, dict):
        return fail("first_pass_not_object", "first_pass must be an object")
    if first.get("resolution_fraction") != FIRST_PASS_RESOLUTION_FRACTION:
        return fail(
            "first_pass_not_half_resolution",
            "the first pass must be half-resolution "
            f"({FIRST_PASS_RESOLUTION_FRACTION}), got "
            f"{first.get('resolution_fraction')!r}",
        )
    if first.get("completed") is not True:
        return fail(
            "first_pass_not_completed",
            "the half-resolution first pass must complete before the second pass",
        )
    second = run["second_pass"]
    if not isinstance(second, dict):
        return fail("second_pass_not_object", "second_pass must be an object")
    if second.get("completed") is True and second.get("reuses_first_pass") is not True:
        return fail(
            "second_pass_does_not_reuse_first",
            "a completed second pass must reuse the first pass, not redo it",
        )
    if run["two_seeds_first_shot"] is not True:
        return fail(
            "two_seeds_required",
            "generate two seeds of the first shot before continuing",
        )
    if run["preview_reviewed_full_size"] is not True:
        return fail(
            "preview_not_reviewed_full_size",
            "look at the first-shot takes at full size before choosing one",
        )
    if run["only_liked_completed"] is not True:
        return fail(
            "unliked_takes_completed",
            "only complete the takes you like; do not finish the rest",
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
    report = check_freevideo_preview_first(params.get("run"))
    report_path = out_dir / "freevideo_preview_first_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_preview_first_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_preview_first_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "run": {"type": "object"},
                },
                "required": ["run"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "FreeVideo preview-first gate: half-resolution first "
                "pass, second pass reuses it, two seeds of the first "
                "shot reviewed at full size, only liked takes completed."
            ),
        )
    )
    return ["qa.freevideo_preview_first_gate"]


__all__ = [
    "FIRST_PASS_RESOLUTION_FRACTION",
    "check_freevideo_preview_first",
    "register_freevideo_preview_first_gate_capabilities_once",
]
