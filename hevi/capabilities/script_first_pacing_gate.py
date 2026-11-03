"""Script-first pacing gate (``qa.script_first_pacing_gate``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 7 (iart): the script comes first and the voice is the
spine of the film. Pictures only illustrate the sentence being spoken.
In hevi's caliber:

1. A script must be present before any picture plan is judged, with a
   word count and a speaking rate supplied by the caller. The rate is
   never defaulted: the commonly cited 2.3 words per second may only
   appear as a registered reference value, explicitly marked as such,
   and must never silently stand in for a measured rate.
2. One analogy runs through the whole film. A second, competing
   analogy declared mid-plan fails.
3. The pacing table must declare every beat's start, end, and spoken
   sentence, and beats must tile the script time implied by the
   caller-given rate within a 1ms rounding tolerance.

This module judges plans only. It records no audio and calls no
transcriber.
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

_EPS = 0.001


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_script_first_pacing(plan: Any) -> dict[str, Any]:
    """Judge one script-first pacing plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    beats_out: list[dict[str, Any]] = []
    implied_s: float | None = None
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
            "implied_duration_s": None,
            "beats": [],
        }
    script = plan.get("script")
    word_count: int | None = None
    rate: float | None = None
    if not isinstance(script, dict):
        issues.append(_issue("script_missing", "plan must declare a script first"))
    else:
        if not _is_nonempty_str(script.get("text")):
            issues.append(_issue("script_text_missing", "script must carry its text"))
        words = script.get("word_count")
        if not isinstance(words, int) or isinstance(words, bool) or words <= 0:
            issues.append(
                _issue("word_count_missing", "script must declare a positive word_count")
            )
        else:
            word_count = words
        rate_value = script.get("words_per_second")
        if not _is_number(rate_value) or rate_value <= 0:
            issues.append(
                _issue(
                    "speaking_rate_missing",
                    "script must declare a caller-given words_per_second; "
                    "no default rate is applied",
                )
            )
        else:
            rate = float(rate_value)
        reference = script.get("rate_reference")
        if reference is not None:
            if not (
                isinstance(reference, dict)
                and reference.get("registered_reference") is True
                and _is_number(reference.get("words_per_second"))
            ):
                issues.append(
                    _issue(
                        "rate_reference_unmarked",
                        "a cited rate must be marked registered_reference "
                        "with its value; it never replaces a measured rate",
                    )
                )
    analogies = plan.get("analogies")
    if analogies is not None:
        if not isinstance(analogies, list) or not analogies:
            issues.append(
                _issue("analogy_missing", "plan must declare exactly one analogy")
            )
        elif len(analogies) > 1:
            issues.append(
                _issue(
                    "analogy_switched",
                    "one analogy must run through the whole film; "
                    f"{len(analogies)} were declared",
                )
            )
        elif not _is_nonempty_str(analogies[0]):
            issues.append(_issue("analogy_missing", "analogy must be a non-empty string"))
    else:
        issues.append(_issue("analogy_missing", "plan must declare exactly one analogy"))
    if word_count is not None and rate is not None:
        implied_s = word_count / rate
    beats = plan.get("beats")
    if not isinstance(beats, list) or not beats:
        issues.append(_issue("beats_missing", "plan must declare a non-empty beats list"))
        beats = beats if isinstance(beats, list) else []
    cursor = 0.0
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            issues.append(
                _issue("beat_not_object", f"beats[{index}] must be an object")
            )
            continue
        start = beat.get("start_s")
        end = beat.get("end_s")
        if not _is_number(start) or not _is_number(end) or end <= start:
            issues.append(
                _issue("beat_window_invalid", f"beats[{index}] must declare start_s < end_s")
            )
            continue
        if abs(float(start) - cursor) > _EPS:
            issues.append(
                _issue(
                    "beat_gap_or_overlap",
                    f"beats[{index}] starts at {start}, expected {cursor}",
                )
            )
        if not _is_nonempty_str(beat.get("sentence")):
            issues.append(
                _issue(
                    "beat_sentence_missing",
                    f"beats[{index}] must name the sentence it illustrates",
                )
            )
        beats_out.append({"id": beat.get("id"), "start_s": start, "end_s": end})
        cursor = float(end)
    if implied_s is not None and beats_out:
        if abs(cursor - implied_s) > _EPS:
            issues.append(
                _issue(
                    "beats_do_not_cover_script",
                    f"beats end at {cursor}, script implies {implied_s} "
                    "at the caller-given rate",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "implied_duration_s": implied_s,
        "beats": beats_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_script_first_pacing(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "script_first_pacing_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_script_first_pacing_gate_capabilities_once() -> list[str]:
    """Register ``qa.script_first_pacing_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.script_first_pacing_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Script-first pacing gate: the script comes first, the "
                "speaking rate is caller-given and never defaulted, one "
                "analogy runs through the whole film, and beats tile the "
                "script time. Plans are judged, never re-paced."
            ),
            line="qa",
        )
    )
    return ["qa.script_first_pacing_gate"]


register_script_first_pacing_gate_capabilities_once()
