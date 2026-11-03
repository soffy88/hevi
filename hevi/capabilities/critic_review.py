"""Independent critic review record and revision pixel identity.

Clean-room rewrite of the *review discipline* of
``win4r/video-director`` (MIT; see VIDEO_DIRECTOR_ATTRIBUTION.md):
a reviewer who did not build the film scores it on nine axes with
frame/timestamp evidence, defects are ranked P0/P1/P2, the film
only ships when every axis scores at least 8 with no P0, and at
most one fix round is allowed. No text, code or script from the
source repository is copied here.

A review record is a report only: recording it never modifies a
film, a frame or a timeline. The pixel-identity check compares
two directories of *pre-encode* grabbed frames (same-name PNGs);
frames outside the declared fix ranges must be pixel-identical.
Two MP4 files must never be diffed directly (an encoder spreads
differences either side of an edit point), so passing an MP4 --
or any file -- where a frame directory is expected is an error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

AXES = (
    "Hook",
    "Clarity",
    "Readability",
    "Motion quality",
    "Rhythm and variety",
    "Composition and look",
    "Continuity",
    "Truth",
    "Sound sync",
)
SHIP_MIN_SCORE = 8
MAX_FIX_ROUND = 1
SEVERITIES = ("P0", "P1", "P2")
_SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2}
# Evidence must cite a frame or a timestamp, not just an opinion.
_EVIDENCE_RE = re.compile(
    r"(\d+:\d{2}|\d+\.\d+\s*s\b|frame\s*#?\s*\d+|\bt\s*=\s*\d|@\s*\d+(\.\d+)?s?)",
    re.IGNORECASE,
)
_INDEX_RE = re.compile(r"(\d+)(?!.*\d)")


def _normalise_axis_name(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    key = " ".join(name.strip().lower().replace("_", " ").replace("-", " ").split())
    for axis in AXES:
        if " ".join(axis.lower().split()) == key:
            return axis
    return None


def _parse_axes(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalise dict- or list-shaped axis scores into {axis: {...}}."""
    parsed: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = []
        for entry in raw:
            if isinstance(entry, dict):
                items.append((entry.get("axis", entry.get("name")), entry))
            else:
                items.append((None, entry))
    else:
        raise CapabilityError("qa.critic_review: review axes must be an object or a list")
    for name, value in items:
        axis = _normalise_axis_name(name)
        if axis is None:
            raise CapabilityError(f"qa.critic_review: unknown review axis: {name!r}")
        if axis in parsed:
            raise CapabilityError(f"qa.critic_review: duplicate review axis: {axis}")
        if isinstance(value, dict) and "score" in value:
            parsed[axis] = dict(value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed[axis] = {"score": value}
        else:
            raise CapabilityError(
                f"qa.critic_review: axis {axis} needs a score (got {value!r})"
            )
    return parsed


def record_critic_review(review: dict[str, Any]) -> dict[str, Any]:
    """Validate a critic review record and compute its verdict.

    Verdicts: ``"ship"`` (every axis >= 8 and no P0 defect),
    ``"one_more_pass"`` (otherwise), ``"fail"`` (fix_round > 1,
    i.e. the one-fix-round discipline is broken). Structural
    problems (missing axis, out-of-range score, evidence without a
    frame/timestamp cite) raise :class:`CapabilityError`.
    """
    if not isinstance(review, dict):
        raise CapabilityError("qa.critic_review: review must be an object (dict)")
    problems: list[str] = []
    axes_raw = review.get("axes", review.get("scores"))
    if axes_raw is None:
        raise CapabilityError("qa.critic_review: review has no axes/scores")
    axes = _parse_axes(axes_raw)
    for axis in AXES:
        if axis not in axes:
            problems.append(f"missing axis: {axis}")
    scores: dict[str, int] = {}
    for axis, entry in axes.items():
        score = entry.get("score")
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 10:
            problems.append(f"axis {axis}: score must be an integer 1-10, got {score!r}")
            continue
        scores[axis] = score
        evidence = entry.get("evidence", entry.get("note", ""))
        if not isinstance(evidence, str) or not evidence.strip():
            problems.append(f"axis {axis}: score needs frame/timestamp evidence")
        elif not _EVIDENCE_RE.search(evidence):
            problems.append(
                f"axis {axis}: evidence cites no frame or timestamp: {evidence!r}"
            )
    defects_raw = review.get("defects", [])
    if not isinstance(defects_raw, list):
        problems.append("defects must be a list")
        defects_raw = []
    defects: list[dict[str, Any]] = []
    for idx, entry in enumerate(defects_raw):
        if not isinstance(entry, dict):
            problems.append(f"defect {idx}: must be an object")
            continue
        severity = entry.get("severity")
        if severity not in SEVERITIES:
            problems.append(f"defect {idx}: severity must be one of {list(SEVERITIES)}, got {severity!r}")
            continue
        description = entry.get("description", entry.get("text", ""))
        if not isinstance(description, str) or not description.strip():
            problems.append(f"defect {idx}: needs a non-empty description")
            continue
        defects.append({
            "severity": severity,
            "description": description.strip(),
            "axis": entry.get("axis"),
            "evidence": entry.get("evidence"),
            "fix": entry.get("fix"),
        })
    if problems:
        raise CapabilityError(
            "qa.critic_review: invalid review record: " + "; ".join(problems)
        )
    defects.sort(key=lambda d: _SEVERITY_RANK[d["severity"]])
    fix_round = review.get("fix_round", 0)
    if isinstance(fix_round, float) and fix_round.is_integer():
        fix_round = int(fix_round)
    if not isinstance(fix_round, int) or isinstance(fix_round, bool) or fix_round < 0:
        raise CapabilityError(f"qa.critic_review: fix_round must be a non-negative integer, got {fix_round!r}")
    has_p0 = any(d["severity"] == "P0" for d in defects)
    weakest_axis = min(scores, key=lambda a: scores[a]) if scores else None
    if fix_round > MAX_FIX_ROUND:
        verdict = "fail"
        reason = f"fix_round {fix_round} exceeds the one-fix-round limit ({MAX_FIX_ROUND})"
    elif all(score >= SHIP_MIN_SCORE for score in scores.values()) and not has_p0:
        verdict = "ship"
        reason = f"every axis >= {SHIP_MIN_SCORE} and no P0 defect"
    else:
        verdict = "one_more_pass"
        weak = [f"{a}={scores[a]}" for a in AXES if scores[a] < SHIP_MIN_SCORE]
        parts = []
        if weak:
            parts.append(f"axes below {SHIP_MIN_SCORE}: {', '.join(weak)}")
        if has_p0:
            parts.append("P0 defect present")
        reason = "; ".join(parts) or "review does not meet the ship bar"
    report: dict[str, Any] = {
        "capability": "qa.critic_review",
        "verdict": verdict,
        "reason": reason,
        "scores": scores,
        "weakest_axis": weakest_axis,
        "defects": defects,
        "defect_count": len(defects),
        "p0_count": sum(1 for d in defects if d["severity"] == "P0"),
        "fix_round": fix_round,
        "film": review.get("film"),
        "reviewer": review.get("reviewer"),
        "weakest_shot": review.get("weakest_shot"),
        "notes": review.get("notes"),
    }
    claimed = review.get("verdict")
    if claimed is not None and claimed != verdict:
        report["claimed_verdict"] = claimed
        report["verdict_note"] = (
            f"claimed verdict {claimed!r} does not match computed verdict "
            f"{verdict!r}; the computed verdict stands"
        )
    return report


def _frame_time(name: str, fps: float) -> float | None:
    match = _INDEX_RE.search(Path(name).stem)
    if match is None:
        return None
    return int(match.group(1)) / fps


def _is_in_ranges(t: float, ranges: list[tuple[float, float]]) -> bool:
    return any(start <= t < end or (start == end and t == start) for start, end in ranges)


def _check_dir(path: Any, label: str) -> Path:
    if isinstance(path, (str, Path)) and str(path).lower().endswith(".mp4"):
        raise CapabilityError(
            f"qa.critic_review: {label} must be a directory of pre-encode "
            f"frame PNGs, not an MP4 file: {path}"
        )
    resolved = Path(path)
    if resolved.is_file():
        raise CapabilityError(
            f"qa.critic_review: {label} must be a frame directory, got file: {resolved}"
        )
    if not resolved.is_dir():
        raise CapabilityError(f"qa.critic_review: {label} directory not found: {resolved}")
    return resolved


def check_revision_pixel_identity(
    before_dir: Path | str,
    after_dir: Path | str,
    fixed_ranges_sec: list[Any],
    fps: float,
    tolerance: int = 0,
) -> dict[str, Any]:
    """Compare pre-encode frame grabs; outside fix ranges pixels must match.

    ``fixed_ranges_sec`` is a list of ``[start, end]`` second ranges
    (or ``{"start": .., "end": ..}`` dicts) that were allowed to
    change. ``tolerance`` is the maximum allowed per-channel absolute
    difference (0 = pixel-identical).
    """
    before = _check_dir(before_dir, "before_dir")
    after = _check_dir(after_dir, "after_dir")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or float(fps) <= 0:
        raise CapabilityError(f"qa.critic_review: fps must be a positive number, got {fps!r}")
    fps_f = float(fps)
    if not isinstance(tolerance, int) or isinstance(tolerance, bool) or tolerance < 0:
        raise CapabilityError(f"qa.critic_review: tolerance must be a non-negative integer, got {tolerance!r}")
    ranges: list[tuple[float, float]] = []
    if not isinstance(fixed_ranges_sec, list):
        raise CapabilityError("qa.critic_review: fixed_ranges_sec must be a list of [start, end] ranges")
    for entry in fixed_ranges_sec:
        if isinstance(entry, dict):
            start, end = entry.get("start"), entry.get("end")
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            start, end = entry
        else:
            raise CapabilityError(f"qa.critic_review: bad fix range: {entry!r}")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise CapabilityError(f"qa.critic_review: fix range needs numeric start/end: {entry!r}")
        ranges.append((float(start), float(end)))
    before_pngs = {p.name: p for p in before.glob("*.png")}
    after_pngs = {p.name: p for p in after.glob("*.png")}
    names = sorted(set(before_pngs) | set(after_pngs))
    if not names:
        raise CapabilityError(
            f"qa.critic_review: no PNG frames in {before} or {after}"
        )
    changed: list[dict[str, Any]] = []
    compared = 0
    for name in names:
        t = _frame_time(name, fps_f)
        if t is None:
            raise CapabilityError(
                f"qa.critic_review: frame file {name!r} carries no frame index"
            )
        if name not in before_pngs or name not in after_pngs:
            changed.append({
                "file": name, "t_sec": round(t, 3),
                "max_diff": None,
                "reason": "present in only one frame directory",
            })
            continue
        if _is_in_ranges(t, ranges):
            continue
        with Image.open(before_pngs[name]) as ia, Image.open(after_pngs[name]) as ib:
            if ia.size != ib.size:
                changed.append({
                    "file": name, "t_sec": round(t, 3), "max_diff": None,
                    "reason": f"frame size changed {ia.size} -> {ib.size}",
                })
                continue
            diff = ImageChops.difference(ia.convert("RGB"), ib.convert("RGB"))
            extrema = diff.getextrema()
            max_diff = max(hi for _, hi in extrema)
        compared += 1
        if max_diff > tolerance:
            changed.append({
                "file": name, "t_sec": round(t, 3), "max_diff": int(max_diff),
                "reason": f"max pixel difference {max_diff} exceeds tolerance {tolerance}",
            })
    status = "fail" if changed else "pass"
    return {
        "capability": "qa.critic_review",
        "check": "revision_pixel_identity",
        "status": status,
        "pass": status == "pass",
        "compared_frames": compared,
        "changed_frames": changed,
        "changed_count": len(changed),
        "fixed_ranges_sec": [[s, e] for s, e in ranges],
        "fps": fps_f,
        "tolerance": tolerance,
        "only_in_before": sorted(set(before_pngs) - set(after_pngs)),
        "only_in_after": sorted(set(after_pngs) - set(before_pngs)),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = str(params.get("action", "record"))
    if action == "record":
        report = record_critic_review(params.get("review", {}))
        report_path = out_dir / "critic_review_report.json"
    elif action == "pixel_identity":
        report = check_revision_pixel_identity(
            params["before_dir"], params["after_dir"],
            params.get("fixed_ranges_sec", []),
            float(params["fps"]),
            tolerance=int(params.get("tolerance", 0)),
        )
        report_path = out_dir / "revision_pixel_identity_report.json"
    else:
        raise CapabilityError(
            f"qa.critic_review: unknown action {action!r}; known: record, pixel_identity"
        )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    verdict = report.get("verdict", report.get("status"))
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": verdict,
            "pass": verdict in ("ship", "pass"),
        },
    )


def register_critic_review_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.critic_review",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "review": {"type": "object"},
                    "before_dir": {"type": "string"},
                    "after_dir": {"type": "string"},
                    "fixed_ranges_sec": {"type": "array"},
                    "fps": {"type": "number", "exclusiveMinimum": 0},
                    "tolerance": {"type": "integer", "minimum": 0},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Independent critic review record: nine axes scored "
                "1-10 with frame/timestamp evidence, P0/P1/P2 defects "
                "ranked, ship only when every axis >= 8 and no P0, at "
                "most one fix round; plus revision pixel identity over "
                "pre-encode frame directories (never MP4 diffs). "
                "Report only; a review never modifies a film."
            ),
            line="qa",
        )
    )
    return ["qa.critic_review"]


register_critic_review_capabilities_once()
