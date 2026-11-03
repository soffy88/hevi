"""Storyboard fidelity gate (``qa.storyboard_fidelity_gate``).

Clean-room restatement of the storyboard-contract discipline
described in the Infinite Creation review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a storyboard is a contract,
not a suggestion. Every beat names its provenance, the beats tile
the declared duration with no gap and no overlap, no beat repeats
another, and no beat hides a character behind a pronoun. A beat
whose source is still unconfirmed (``tbd``) can never pass under
strict fidelity: it is either confirmed before generation or the
plan is not generation-ready.

This module judges plans only. It never generates, never calls a
model, and never touches a budget. Pronoun detection is
deliberately narrow: English third-person pronouns matched on word
boundaries, and Chinese third-person pronouns as characters. The
character ``qi`` is excluded on purpose: it appears inside common
unrelated words, and flagging it would punish ordinary text.
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

_SOURCES = ("original", "added", "tbd")
_PRONOUNS_EN = (
    "he",
    "she",
    "it",
    "they",
    "him",
    "her",
    "his",
    "their",
    "them",
    "its",
)
_PRONOUN_RE = re.compile(
    r"\b(" + "|".join(_PRONOUNS_EN) + r")\b", re.IGNORECASE
)
_PRONOUNS_ZH = ("他们", "她们", "它们", "他", "她", "它")
_TOL = 1e-3


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.storyboard_fidelity_gate: {detail}"}
    issue.update(extra)
    return issue


def _pronouns_in(text: str) -> list[str]:
    found = [m.group(1).lower() for m in _PRONOUN_RE.finditer(text)]
    for pronoun in _PRONOUNS_ZH:
        if pronoun in text:
            found.append(pronoun)
    return sorted(set(found))


def check_storyboard_fidelity(plan: Any) -> dict[str, Any]:
    """Judge one storyboard plan.

    ``plan`` carries ``beats`` (each with ``start_s``, ``end_s``,
    ``text`` and ``source``), ``total_duration_s``, and optional
    ``strict_fidelity`` (default True). Verdict ``pass`` means the
    beats tile the duration, every source is declared and, under
    strict fidelity, confirmed, no beat repeats another, and no
    beat uses a pronoun. Unconfirmed beats under non-strict
    fidelity are ``not_checked``, never passes.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("storyboard plan must be an object")
    issues: list[dict[str, Any]] = []
    not_checked: list[dict[str, Any]] = []
    beats = plan.get("beats")
    total = plan.get("total_duration_s")
    strict = bool(plan.get("strict_fidelity", True))
    if not isinstance(beats, list) or not beats:
        raise CapabilityError("storyboard plan requires a non-empty beats list")
    if not isinstance(total, (int, float)) or total <= 0:
        raise CapabilityError("storyboard plan requires total_duration_s > 0")

    seen_texts: dict[str, int] = {}
    previous_end: float | None = None
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            issues.append(_issue("beat_not_object", f"beat {index} is not an object"))
            continue
        start = beat.get("start_s")
        end = beat.get("end_s")
        text = beat.get("text")
        source = beat.get("source")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            issues.append(_issue("beat_time_missing", f"beat {index} lacks numeric start_s/end_s"))
            continue
        if end <= start:
            issues.append(_issue("beat_empty_window", f"beat {index} ends at or before it starts"))
        if previous_end is None:
            if abs(start) > _TOL:
                issues.append(
                    _issue("coverage_gap", f"first beat starts at {start}, not 0", beat=index)
                )
        elif abs(start - previous_end) > _TOL:
            issues.append(
                _issue(
                    "coverage_gap",
                    f"beat {index} starts at {start}, previous beat ends at {previous_end}",
                    beat=index,
                )
            )
        previous_end = end
        if not isinstance(text, str) or not text.strip():
            issues.append(_issue("beat_text_empty", f"beat {index} has no text"))
            continue
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        if normalized in seen_texts:
            issues.append(
                _issue(
                    "duplicate_beat",
                    f"beat {index} repeats beat {seen_texts[normalized]}",
                    beat=index,
                )
            )
        else:
            seen_texts[normalized] = index
        pronouns = _pronouns_in(text)
        if pronouns:
            issues.append(
                _issue(
                    "pronoun_in_beat",
                    f"beat {index} uses pronoun(s): {', '.join(pronouns)}",
                    beat=index,
                    pronouns=pronouns,
                )
            )
        if source not in _SOURCES:
            issues.append(
                _issue("source_undeclared", f"beat {index} source must be one of {_SOURCES}", beat=index)
            )
        elif source == "tbd":
            if strict:
                issues.append(
                    _issue("unconfirmed_tbd", f"beat {index} is tbd under strict fidelity", beat=index)
                )
            else:
                not_checked.append(
                    {"code": "tbd_unconfirmed", "detail": f"beat {index} is tbd", "beat": index}
                )
    if previous_end is not None and abs(previous_end - total) > _TOL:
        issues.append(
            _issue(
                "coverage_gap",
                f"last beat ends at {previous_end}, total duration is {total}",
            )
        )
    if issues:
        verdict = "fail"
    elif not_checked:
        verdict = "not_checked"
    else:
        verdict = "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": not_checked,
        "beat_count": len(beats),
        "strict_fidelity": strict,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_storyboard_fidelity(params.get("plan"))
    report_path = out_dir / "storyboard_fidelity.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_storyboard_fidelity_gate_capabilities_once() -> list[str]:
    """Register ``qa.storyboard_fidelity_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.storyboard_fidelity_gate",
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
                "Storyboard fidelity gate: beats must tile the declared "
                "duration, name a declared source, never repeat, and never "
                "use a pronoun; unconfirmed beats fail under strict fidelity."
            ),
        )
    )
    return ["qa.storyboard_fidelity_gate"]


__all__ = ["check_storyboard_fidelity", "register_storyboard_fidelity_gate_capabilities_once"]
