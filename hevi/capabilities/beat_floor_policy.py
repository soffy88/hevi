"""Beat floor policy + short-beat merging (``qa.beat_floor_policy``).

Gap 6 from ``hevi-vs-h3-exemplar-prompts-v2.md``: the H3 exemplar's
``MIN_BEAT_S = 1.0`` default (``story.prompt_compiler`` gate 1) rejects
five segments' sub-second match-on-action opening beats (0.573-0.8s).
Two remedies, both explicit, neither silent:

1. **Floor review.** A caller may declare a lower ``beat_floor_s``
   for one plan, but only with a non-empty ``reason``; the reason is
   recorded in the evidence. Declaring nothing keeps the default
   floor, byte for byte the same behaviour as before: the default
   value is never changed by this module (it must stay equal to
   ``story.prompt_compiler.MIN_BEAT_S``; a test asserts the equality).
2. **Merging.** ``merge_short_beats`` folds a short beat into its
   neighbour, preserving the tiling (no gap, no overlap, total
   duration unchanged) and preserving every action / camera text:
   merged text is concatenated and annotated with its source window,
   and every folded boundary is recorded in an audit list whose
   original start/end timecodes stay readable.

This module judges plans only. It never generates, never calls a
model, never touches a budget. It does not re-implement beat
coverage: tiling is checked by ``story.prompt_compiler`` gate 1
and by ``qa.three_layer_clip``; merging requires a tiled input and
refuses (``ok: False``) an untiled one instead of inventing times.

No dance-chain vocabulary lives here: the Rev.1.4 motion-chain
document was never supplied, and no C-chain is invented.
"""

from __future__ import annotations

import copy
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

# Must stay equal to story.prompt_compiler.MIN_BEAT_S. The default
# path (no policy declared) behaves exactly as gate 1 always did.
DEFAULT_BEAT_FLOOR_S = 1.0

_EPS = 1e-9


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fmt_time(seconds: float) -> str:
    # Millisecond precision, matching qa.three_layer_clip._fmt_time:
    # 1.083 and 13.268 survive verbatim.
    return f"{float(seconds):.3f}"


def resolve_beat_floor(policy: Any = None) -> dict[str, Any]:
    """Resolve the effective beat floor for one plan.

    ``policy`` is ``None``/``{}`` for the default path, or an object
    with ``beat_floor_s`` (a positive number) and, when the declared
    floor is below the default, a non-empty ``reason``. Returns
    ``floor_s`` / ``reviewed`` / ``reason`` / ``issues`` / ``ok``.
    Never raises for a bad policy; callers that need a hard refusal
    use ``authorize_beat_floor``.
    """
    issues: list[dict[str, Any]] = []
    if policy is None:
        return {
            "floor_s": DEFAULT_BEAT_FLOOR_S,
            "reviewed": False,
            "reason": None,
            "issues": issues,
            "ok": True,
        }
    if not isinstance(policy, dict):
        return {
            "floor_s": DEFAULT_BEAT_FLOOR_S,
            "reviewed": False,
            "reason": None,
            "issues": [{
                "code": "beat_floor_policy_not_object",
                "detail": "qa.beat_floor_policy: beat floor policy must "
                          "be an object",
            }],
            "ok": False,
        }
    floor = policy.get("beat_floor_s", DEFAULT_BEAT_FLOOR_S)
    reason = policy.get("reason")
    if not _is_number(floor) or float(floor) <= 0:
        issues.append({
            "code": "invalid_beat_floor",
            "detail": "qa.beat_floor_policy: beat_floor_s must be a "
                      f"positive number, got {floor!r}",
        })
        return {
            "floor_s": DEFAULT_BEAT_FLOOR_S,
            "reviewed": False,
            "reason": None,
            "issues": issues,
            "ok": False,
        }
    floor = float(floor)
    reviewed = False
    if floor < DEFAULT_BEAT_FLOOR_S - _EPS:
        if not isinstance(reason, str) or not reason.strip():
            issues.append({
                "code": "floor_review_reason_missing",
                "detail": "qa.beat_floor_policy: a beat floor below the "
                          f"{DEFAULT_BEAT_FLOOR_S:g}s default needs a "
                          "non-empty 'reason'; the default path is "
                          "unchanged and the review is recorded in "
                          "the evidence",
            })
        else:
            reviewed = True
    return {
        "floor_s": floor,
        "reviewed": reviewed,
        "reason": reason.strip() if isinstance(reason, str) and reason.strip() else None,
        "issues": issues,
        "ok": not issues,
    }


def check_beat_floor(beats: Any, policy: Any = None) -> dict[str, Any]:
    """Judge every beat's span against the resolved floor.

    Returns a report; never raises for a bad plan. Tiling is not
    judged here (gate 1 / three-layer tiling own that); spans are
    judged beat by beat, in order.
    """
    resolved = resolve_beat_floor(policy)
    floor = resolved["floor_s"]
    issues: list[dict[str, Any]] = list(resolved["issues"])
    rows: list[dict[str, Any]] = []
    if not isinstance(beats, list) or not beats:
        issues.append({
            "code": "beats_missing",
            "detail": "qa.beat_floor_policy: beats must be a non-empty list",
        })
        return {
            "ok": False,
            "verdict": "fail",
            "floor_s": floor,
            "reviewed": resolved["reviewed"],
            "reason": resolved["reason"],
            "issues": issues,
            "beats": rows,
        }
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            issues.append({
                "code": "beat_not_object",
                "detail": f"qa.beat_floor_policy: beat {index} must be "
                          "an object",
            })
            rows.append({"beat_index": index, "span_s": None, "under_floor": None})
            continue
        start, end = beat.get("t_start_s"), beat.get("t_end_s")
        if not _is_number(start) or not _is_number(end):
            issues.append({
                "code": "beat_without_window",
                "detail": f"qa.beat_floor_policy: beat {index} needs "
                          "numeric t_start_s and t_end_s",
            })
            rows.append({"beat_index": index, "span_s": None, "under_floor": None})
            continue
        span = float(end) - float(start)
        under = span < floor - _EPS
        rows.append({
            "beat_index": index,
            "t_start_s": float(start),
            "t_end_s": float(end),
            "span_s": span,
            "under_floor": under,
        })
        if under:
            issues.append({
                "code": "beat_under_floor",
                "detail": f"qa.beat_floor_policy: beat {index} spans "
                          f"{_fmt_time(span)}s ({_fmt_time(float(start))}-"
                          f"{_fmt_time(float(end))}s), under the "
                          f"{_fmt_time(floor)}s floor"
                          + (" (reviewed floor)" if resolved["reviewed"] else ""),
            })
    ok = not issues
    return {
        "ok": ok,
        "verdict": "pass" if ok else "fail",
        "floor_s": floor,
        "reviewed": resolved["reviewed"],
        "reason": resolved["reason"],
        "issues": issues,
        "beats": rows,
    }


def authorize_beat_floor(beats: Any, policy: Any = None) -> dict[str, Any]:
    """Approve a beat list against the floor, or refuse it loudly."""
    report = check_beat_floor(beats, policy)
    if not report["ok"]:
        raise CapabilityError(
            "qa.beat_floor_policy: beat floor refused: "
            + "; ".join(i["detail"] for i in report["issues"])
        )
    return report


def _beat_window(beat: dict[str, Any]) -> tuple[float, float] | None:
    start, end = beat.get("t_start_s"), beat.get("t_end_s")
    if not _is_number(start) or not _is_number(end):
        return None
    return float(start), float(end)


def _join_text(first: Any, second: Any, label: str) -> Any:
    """Concatenate two text fields, annotating the merged source.

    If only one side carries text, it is kept verbatim. If both do,
    the second is appended with its source window so no wording is
    lost and the fold stays auditable.
    """
    f = first if isinstance(first, str) and first.strip() else None
    s = second if isinstance(second, str) and second.strip() else None
    if f is not None and s is not None and f.strip() != s.strip():
        return f"{f.strip()} [merged {label}: {s.strip()}]"
    return f if f is not None else (s if s is not None else first)


def _merge_pair(
    first: dict[str, Any],
    second: dict[str, Any],
) -> dict[str, Any]:
    """Fold ``second`` into ``first``; windows must already be adjacent."""
    merged = copy.deepcopy(first)
    f_start, f_end = _beat_window(first)
    s_start, s_end = _beat_window(second)
    merged["t_start_s"] = f_start
    merged["t_end_s"] = s_end
    label = f"{_fmt_time(s_start)}-{_fmt_time(s_end)}s"
    merged["action"] = _join_text(first.get("action"), second.get("action"), label)
    for key in ("camera_move", "sound", "landing"):
        if key in first or key in second:
            merged[key] = _join_text(first.get(key), second.get(key), label)
    cam1, cam2 = first.get("camera"), second.get("camera")
    if isinstance(cam1, dict) and isinstance(cam2, dict) and cam1 != cam2:
        merged["merged_camera_note"] = (
            "merged cameras: first beat camera "
            f"{json.dumps(cam1, ensure_ascii=False)}; folded beat camera "
            f"{json.dumps(cam2, ensure_ascii=False)}"
        )
    elif isinstance(cam2, dict) and not isinstance(cam1, dict):
        merged["camera"] = copy.deepcopy(cam2)
    if isinstance(first.get("action_clauses"), list) or isinstance(second.get("action_clauses"), list):
        clauses: list[str] = []
        for beat in (first, second):
            clauses.extend(c for c in (beat.get("action_clauses") or []) if isinstance(c, str))
        merged["action_clauses"] = clauses
    return merged


def merge_short_beats(
    beats: Any,
    *,
    floor_s: float | None = None,
    policy: Any = None,
) -> dict[str, Any]:
    """Fold beats shorter than the floor into a neighbour.

    ``floor_s`` wins over ``policy`` when both are given; otherwise
    ``policy`` resolves through :func:`resolve_beat_floor` (a
    reviewed lower floor needs its reason). The input must tile:
    each beat starts where the previous ends (within 1e-9).
    Folding prefers the next beat; a short final beat folds into
    the previous one. Total duration is unchanged and every folded
    boundary is recorded in ``audit`` with its original timecodes.
    Returns ``ok`` / ``beats`` / ``audit`` / ``issues`` /
    ``floor_s`` / ``reviewed`` / ``reason`` /
    ``all_above_floor`` / ``total_duration_s``; never raises for a
    bad plan.
    """
    if policy is not None:
        resolved = resolve_beat_floor(policy)
        if floor_s is None:
            floor = resolved["floor_s"]
        else:
            floor = float(floor_s)
            resolved = {"reviewed": False, "reason": None, "issues": [], "ok": True}
    elif floor_s is not None:
        if not _is_number(floor_s) or float(floor_s) <= 0:
            return {
                "ok": False,
                "beats": copy.deepcopy(beats) if isinstance(beats, list) else [],
                "audit": [],
                "issues": [{
                    "code": "invalid_beat_floor",
                    "detail": "qa.beat_floor_policy: floor_s must be a "
                              f"positive number, got {floor_s!r}",
                }],
                "floor_s": DEFAULT_BEAT_FLOOR_S,
                "reviewed": False,
                "reason": None,
                "all_above_floor": False,
                "total_duration_s": None,
            }
        floor = float(floor_s)
        resolved = {"reviewed": False, "reason": None, "issues": [], "ok": True}
    else:
        resolved = resolve_beat_floor(None)
        floor = resolved["floor_s"]
    issues: list[dict[str, Any]] = list(resolved.get("issues", []))
    if not resolved.get("ok", True):
        return {
            "ok": False,
            "beats": copy.deepcopy(beats) if isinstance(beats, list) else [],
            "audit": [],
            "issues": issues,
            "floor_s": floor,
            "reviewed": resolved.get("reviewed", False),
            "reason": resolved.get("reason"),
            "all_above_floor": False,
            "total_duration_s": None,
        }
    if not isinstance(beats, list) or not beats:
        issues.append({
            "code": "beats_missing",
            "detail": "qa.beat_floor_policy: beats must be a non-empty list",
        })
        return {
            "ok": False, "beats": [], "audit": [], "issues": issues,
            "floor_s": floor, "reviewed": resolved.get("reviewed", False),
            "reason": resolved.get("reason"), "all_above_floor": False,
            "total_duration_s": None,
        }
    windows = [_beat_window(b) if isinstance(b, dict) else None for b in beats]
    if any(w is None for w in windows):
        issues.append({
            "code": "beat_without_window",
            "detail": "qa.beat_floor_policy: every beat needs numeric "
                      "t_start_s and t_end_s before merging",
        })
        return {
            "ok": False, "beats": copy.deepcopy(beats), "audit": [],
            "issues": issues, "floor_s": floor,
            "reviewed": resolved.get("reviewed", False),
            "reason": resolved.get("reason"), "all_above_floor": False,
            "total_duration_s": None,
        }
    for index in range(1, len(windows)):
        if abs(windows[index][0] - windows[index - 1][1]) > _EPS:
            issues.append({
                "code": "beats_not_tiled",
                "detail": "qa.beat_floor_policy: beat "
                          f"{index} starts at {windows[index][0]}s but "
                          f"beat {index - 1} ends at "
                          f"{windows[index - 1][1]}s; merging needs a "
                          "tiled input and invents no times",
            })
            return {
                "ok": False, "beats": copy.deepcopy(beats), "audit": [],
                "issues": issues, "floor_s": floor,
                "reviewed": resolved.get("reviewed", False),
                "reason": resolved.get("reason"), "all_above_floor": False,
                "total_duration_s": None,
            }
    total = sum(w[1] - w[0] for w in windows)
    work: list[dict[str, Any]] = [copy.deepcopy(b) for b in beats]
    audit: list[dict[str, Any]] = []
    while len(work) > 1:
        spans = [_beat_window(b)[1] - _beat_window(b)[0] for b in work]
        short = next((i for i, s in enumerate(spans) if s < floor - _EPS), None)
        if short is None:
            break
        if short < len(work) - 1:
            first, second = work[short], work[short + 1]
            merged = _merge_pair(first, second)
            audit.append({
                "folded_beat_index": short,
                "folded_window": {
                    "t_start_s": _beat_window(second)[0],
                    "t_end_s": _beat_window(second)[1],
                },
                "merged_into_index": short,
                "result_window": {
                    "t_start_s": _beat_window(merged)[0],
                    "t_end_s": _beat_window(merged)[1],
                },
                "floor_s": floor,
            })
            work[short:short + 2] = [merged]
        else:
            first, second = work[short - 1], work[short]
            merged = _merge_pair(first, second)
            audit.append({
                "folded_beat_index": short,
                "folded_window": {
                    "t_start_s": _beat_window(second)[0],
                    "t_end_s": _beat_window(second)[1],
                },
                "merged_into_index": short - 1,
                "result_window": {
                    "t_start_s": _beat_window(merged)[0],
                    "t_end_s": _beat_window(merged)[1],
                },
                "floor_s": floor,
            })
            work[short - 1:short + 1] = [merged]
    new_total = sum(_beat_window(b)[1] - _beat_window(b)[0] for b in work)
    all_above = all(
        _beat_window(b)[1] - _beat_window(b)[0] >= floor - _EPS for b in work
    )
    if abs(new_total - total) > _EPS:  # pragma: no cover - internal guard
        issues.append({
            "code": "merge_changed_total",
            "detail": "qa.beat_floor_policy: merging changed the total "
                      f"duration from {total}s to {new_total}s",
        })
    if not all_above:
        issues.append({
            "code": "single_beat_under_floor",
            "detail": "qa.beat_floor_policy: the whole clip is shorter "
                      f"than the {_fmt_time(floor)}s floor; merging "
                      "cannot invent duration",
        })
    return {
        "ok": not issues,
        "beats": work,
        "audit": audit,
        "issues": issues,
        "floor_s": floor,
        "reviewed": resolved.get("reviewed", False),
        "reason": resolved.get("reason"),
        "all_above_floor": all_above,
        "total_duration_s": total,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    beats = params.get("beats")
    if params.get("merge"):
        report = merge_short_beats(
            beats, floor_s=params.get("floor_s"), policy=params.get("policy")
        )
    else:
        report = check_beat_floor(beats, params.get("policy"))
    report_path = out_dir / "beat_floor_policy.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report.get("verdict", "pass" if report["ok"] else "fail")},
    )


def register_beat_floor_policy_capabilities_once() -> list[str]:
    """Register ``qa.beat_floor_policy`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.beat_floor_policy",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "beats": {"type": "array"},
                    "policy": {"type": "object"},
                    "floor_s": {"type": "number"},
                    "merge": {"type": "boolean"},
                },
                "required": ["beats"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Beat floor policy: judge beat spans against the "
                "1.0s default floor (identical to prompt_compiler "
                "gate 1), or a lower reviewed floor declared with a "
                "non-empty reason, or fold short beats into a "
                "neighbour with an audit trail. Merging preserves "
                "tiling, total duration and all action/camera text. "
                "Judges plans only; no generation, no keys."
            ),
            line="qa",
        )
    )
    return ["qa.beat_floor_policy"]


register_beat_floor_policy_capabilities_once()
