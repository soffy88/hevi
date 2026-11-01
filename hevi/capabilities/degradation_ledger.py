"""Multi-segment degradation ledger (``qa.degradation_ledger``).

Clean-room restatement of the degradation-accounting discipline
behind the PrefixStream relay method (see
``PREFIXSTREAM_ATTRIBUTION.md``): relaying a relay accumulates
error, and the accumulation is *known to be unsolved* -- the
upstream project records it as an open issue and its proposed
remedies (soft masks, an anti-burn LoRA) as unverified
experiments. This ledger therefore never certifies that a long
relay is clean. It only certifies that the accounting exists:
every segment names its context source and its order, every
segment carries a degradation observation, and no experimental
remedy is written into a default plan as if verified.

Verdict discipline follows the house rule: an observation field
left blank is ``not_checked`` -- it is never counted as a pass.
A ledger with only unfilled observations is ``not_checked``
overall; a ledger that claims a verified experimental remedy, or
that breaks the order/source rules, is ``fail``. ``pass`` means
only that the accounting is complete and honest, never that the
video itself is undegraded.

This module judges ledgers only. It never generates, never calls
a model, never touches a budget, and it measures no pixels -- the
observations it checks are caller-supplied records.
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

_EXPERIMENTAL_MEANS = ("soft_mask", "soft_masking", "anti_burn_lora")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.degradation_ledger: {detail}"}
    issue.update(extra)
    return issue


def check_degradation_ledger(ledger: Any) -> dict[str, Any]:
    """Judge one multi-segment degradation ledger.

    ``ledger`` is an object with ``segments`` in play order. Each
    segment declares ``order`` (1-based, consecutive),
    ``context_source`` (with a non-empty ``source_clip_id``), and
    ``degradation_observation``. A missing or blank observation
    (no non-empty ``notes``) is recorded in ``not_checked`` and
    never counts as a pass. ``experimental_means`` entries for
    soft masks / anti-burn LoRA must carry ``verified`` false (or
    ``status`` ``"unverified"``); claiming one verified, or
    listing one under ``default_plan``, fails.
    Returns ``ok`` / ``verdict`` / ``issues`` / ``not_checked`` /
    ``segments``.
    """
    issues: list[dict[str, Any]] = []
    not_checked: list[dict[str, Any]] = []
    segments_out: list[dict[str, Any]] = []
    if not isinstance(ledger, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [
                _issue("ledger_not_object", "degradation ledger must be an object")
            ],
            "not_checked": not_checked,
            "segments": segments_out,
        }
    segments = ledger.get("segments")
    if not isinstance(segments, list) or not segments:
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [
                _issue(
                    "segments_missing",
                    "ledger must declare a non-empty 'segments' list",
                )
            ],
            "not_checked": not_checked,
            "segments": segments_out,
        }
    for index, segment in enumerate(segments):
        expected_order = index + 1
        if not isinstance(segment, dict):
            issues.append(
                _issue(
                    "segment_not_object",
                    f"segment {index} must be an object",
                    segment_index=index,
                )
            )
            segments_out.append(
                {"segment_index": index, "observation": "not_checked"}
            )
            continue
        entry: dict[str, Any] = {"segment_index": index}
        order = segment.get("order")
        if order != expected_order:
            issues.append(
                _issue(
                    "order_not_consecutive",
                    f"segment {index}: 'order' must be consecutive "
                    f"from 1 (expected {expected_order}, got {order!r})",
                    segment_index=index,
                )
            )
        source = segment.get("context_source")
        if index == 0 and source is None:
            entry["fresh_start"] = True
        elif not isinstance(source, dict) or not isinstance(
            source.get("source_clip_id"), str
        ) or not source.get("source_clip_id", "").strip():
            issues.append(
                _issue(
                    "context_source_missing",
                    f"segment {index}: 'context_source' with a "
                    "non-empty 'source_clip_id' is required",
                    segment_index=index,
                )
            )
        observation = segment.get("degradation_observation")
        notes = (
            observation.get("notes")
            if isinstance(observation, dict)
            else None
        )
        if not isinstance(notes, str) or not notes.strip():
            not_checked.append(
                {
                    "code": "degradation_observation_unfilled",
                    "detail": (
                        f"qa.degradation_ledger: segment {index} "
                        "carries no degradation observation; the "
                        "segment is not_checked, never passed"
                    ),
                    "segment_index": index,
                }
            )
            entry["observation"] = "not_checked"
        else:
            entry["observation"] = "recorded"
        for means in segment.get("experimental_means", []) or []:
            if not isinstance(means, dict):
                continue
            name = means.get("name")
            if name not in _EXPERIMENTAL_MEANS:
                continue
            if means.get("verified") is True or means.get("status") == "verified":
                issues.append(
                    _issue(
                        "unverified_means_claimed_verified",
                        f"segment {index}: {name!r} is an unverified "
                        "experiment and must not be claimed verified",
                        segment_index=index,
                    )
                )
            if means.get("in_default_plan"):
                issues.append(
                    _issue(
                        "experimental_means_in_default_plan",
                        f"segment {index}: {name!r} is an unverified "
                        "experiment and must not be written into a "
                        "default plan",
                        segment_index=index,
                    )
                )
        segments_out.append(entry)
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
        "segments": segments_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_degradation_ledger(params.get("ledger"))
    report_path = out_dir / "degradation_ledger.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_degradation_ledger_capabilities_once() -> list[str]:
    """Register ``qa.degradation_ledger`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.degradation_ledger",
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
            description=(
                "Degradation ledger: judge a multi-segment relay "
                "ledger for consecutive order, named context "
                "sources, and filled degradation observations; "
                "unfilled observations are not_checked, never "
                "passes, and unverified experimental remedies must "
                "never be claimed verified or put in a default "
                "plan. Judges ledgers only; measures no pixels."
            ),
            line="qa",
        )
    )
    return ["qa.degradation_ledger"]


register_degradation_ledger_capabilities_once()
