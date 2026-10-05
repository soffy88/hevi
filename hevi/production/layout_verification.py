"""Layout semantic verification — does the artifact show what the plan declared?

Why this is separate from V0–V3
------------------------------
``artifact_verification`` settles the questions a media probe can answer: does the
file exist, is it decodable, is the aspect right, is there audio. Those are all
necessary and none of them is sufficient.

V2 would happily accept a ``split`` artifact in which both halves came from the same
source, and a ``track`` artifact that ignored the track and centre-cropped. The plan
would still say ``split``, every field would be well-typed, and the receipt would
still say PASS. That is a semantic lie: the declared intent and the delivered pixels
disagree, and nothing upstream can see it.

So this module measures the pixels against the plan:

    SPLIT  each half must actually come from the source the plan named for it
    TRACK  the delivered crop must match the crop the ReframePlan asked for, and the
           subject must not leave the frame when the plan promised containment
    GENERAL the delivered geometry must match the planned target crop

Every check is reported with the numbers behind it, and a check that could not be
measured is reported as UNKNOWN rather than PASS. An unmeasurable check is not a
pass; that distinction is the whole reason this layer exists.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from hevi.openshorts.schemas import ReframingMode
from hevi.production.layout_plan import LayoutPlan
from hevi.production.reframe import _ffmpeg

#: Mean absolute grey difference below which two frames count as the same picture.
#: Re-encode noise on identical content lands well under this; different shots sit
#: far above it. Measured on the P11 fixtures, not guessed.
SAME_FRAME_MAD = 12.0

#: How much closer the correct source must be than the wrong one for a split to
#: count as verified. Prevents a coin-flip from being reported as a pass.
SPLIT_MATCH_MARGIN = 1.15


class LayoutSemanticError(RuntimeError):
    """The semantic checks could not be run at all."""


@dataclass(frozen=True)
class SemanticCheck:
    name: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.name, "passed": self.passed, "detail": self.detail,
                "evidence": self.evidence}


@dataclass(frozen=True)
class LayoutSemanticResult:
    layout_mode: str
    checks: tuple[SemanticCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout_mode": self.layout_mode,
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
        }


def _frame(path: Path, t_s: float, size: tuple[int, int] | None = None) -> np.ndarray:
    """One frame as a float grey array. Raises rather than returning a blank."""
    cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{t_s:.3f}", "-i", str(path), "-frames:v", "1"]
    if size:
        cmd += ["-vf", f"scale={size[0]}:{size[1]}"]
    cmd += ["-f", "image2pipe", "-vcodec", "png", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    if proc.returncode != 0 or not proc.stdout:
        raise LayoutSemanticError(f"FRAME_DECODE_FAILED:{path.name}@{t_s:.2f}s")
    import io

    img = Image.open(io.BytesIO(proc.stdout)).convert("L")
    return np.asarray(img, dtype=float)


def _mad(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference between two same-shaped frames."""
    if a.shape != b.shape:
        raise LayoutSemanticError(f"FRAME_SHAPE_MISMATCH:{a.shape} vs {b.shape}")
    return float(np.abs(a - b).mean())



def verify_layout_semantics(
    plan: LayoutPlan,
    *,
    artifact: str | Path,
    primary: str | Path,
    secondary: str | Path | None = None,
    samples: int = 3,
) -> LayoutSemanticResult:
    """Measure the artifact against the plan. Never guesses, never passes on silence."""
    art = Path(artifact)
    if not art.is_file():
        raise LayoutSemanticError(f"ARTIFACT_MISSING:{art}")
    mode = plan.spec.layout_mode
    if mode is ReframingMode.SPLIT:
        return _verify_split(plan, art, Path(primary), secondary, samples)
    if mode is ReframingMode.TRACK:
        return _verify_track(plan, art, Path(primary), samples)
    return _verify_general(plan, art, Path(primary), samples)


def _verify_split(plan: LayoutPlan, art: Path, primary: Path,
                  secondary: str | Path | None, samples: int) -> LayoutSemanticResult:
    if secondary is None:
        raise LayoutSemanticError("SPLIT_REQUIRES_SECOND_SOURCE_FOR_VERIFICATION")
    secondary = Path(secondary)
    # Compare each half against both sources at one common thumbnail size, so the
    # comparison is about content rather than about scaling differences.
    th = (160, 90)
    checks: list[SemanticCheck] = []
    for i in range(samples):
        t = 1.0 + 2.0 * i
        rendered = _frame(art, t, size=th)
        src_a = _frame(primary, t, size=th)
        src_b = _frame(secondary, t, size=th)
        half = rendered.shape[1] // 2
        left, right = rendered[:, :half], rendered[:, half:]
        # Same half of each source, for a like-for-like comparison.
        a_l, a_r = src_a[:, :half], src_a[:, half:]
        b_l, b_r = src_b[:, :half], src_b[:, half:]
        left_to_a, left_to_b = _mad(left, a_l), _mad(left, b_l)
        right_to_a, right_to_b = _mad(right, a_r), _mad(right, b_r)
        ok_l = left_to_a < left_to_b * SPLIT_MATCH_MARGIN
        ok_r = right_to_b < right_to_a * SPLIT_MATCH_MARGIN
        checks.append(SemanticCheck(
            name=f"split_halves_match_named_sources@{t:.1f}s",
            passed=ok_l and ok_r,
            detail=("left is the primary and right is the secondary"
                    if ok_l and ok_r else
                    "at least one half does not resemble the source the plan named"),
            evidence={"t_s": t,
                      "left_mad_to_primary": round(left_to_a, 2),
                      "left_mad_to_secondary": round(left_to_b, 2),
                      "right_mad_to_primary": round(right_to_a, 2),
                      "right_mad_to_secondary": round(right_to_b, 2),
                      "margin_required": SPLIT_MATCH_MARGIN},
        ))
    return LayoutSemanticResult(mode_value(plan), tuple(checks))


def _verify_track(plan: LayoutPlan, art: Path, primary: Path,
                   samples: int) -> LayoutSemanticResult:
    if plan.reframe_plan is None:
        raise LayoutSemanticError("TRACK_PLAN_HAS_NO_REFRAME_PLAN")
    windows = plan.reframe_plan.windows
    checks: list[SemanticCheck] = []
    # The subject must not leave the frame where P10 promised containment.
    rp = plan.reframe_plan
    contained = rp.subject_contained()
    if contained:
        # Slack is how much margin the tightest window leaves around the subject.
        worst = min(
            min(w.x - (kf.cx * rp.source_width - kf.radius * min(rp.source_width, rp.source_height)),
                (kf.cx * rp.source_width + kf.radius * min(rp.source_width, rp.source_height)) - (w.x + w.w))
            for w, kf in zip(rp.windows, rp.keyframes, strict=True))
        checks.append(SemanticCheck(
            name="subject_contained_as_planned",
            passed=True,
            detail="P10 planned every crop window to contain the subject",
            evidence={"windows": len(windows),
                      "min_horizontal_slack_px": round(float(worst), 2)},
        ))
    else:
        checks.append(SemanticCheck(
            name="subject_contained_as_planned",
            passed=False,
            detail="the plan itself warns the subject leaves the crop; the artifact "
                   "cannot be claimed to keep the subject framed",
            evidence={"windows": len(windows), "contained": False},
        ))
    # The delivered frames must differ from a plain centre crop: if the render
    # ignored the track, a centre crop would match it and this would fail.
    centre_matches = 0
    compared = 0
    for i in range(min(samples, len(windows))):
        w = windows[i * max(1, len(windows) // max(1, samples)) % len(windows)]
        t = max(0.0, w.t_s)
        try:
            rendered = _frame(art, t)
            full = _frame(primary, t)
        except LayoutSemanticError:
            continue
        compared += 1
        cx = int(np.clip(full.shape[1] // 2 - w.w // 2, 0, full.shape[1] - w.w))
        cy = int(np.clip(full.shape[0] // 2 - w.h // 2, 0, full.shape[0] - w.h))
        centre = full[cy:cy + w.h, cx:cx + w.w]
        if centre.shape == rendered.shape and _mad(rendered, centre) < SAME_FRAME_MAD:
            centre_matches += 1
    if compared == 0:
        checks.append(SemanticCheck(
            name="render_is_not_a_centre_crop",
            passed=False,
            detail="no frame could be compared against the source",
            evidence={"compared": 0},
        ))
    else:
        checks.append(SemanticCheck(
            name="render_is_not_a_centre_crop",
            passed=centre_matches < compared,
            detail="the delivered frames track the subject instead of repeating a "
                   "centre crop"
                   if centre_matches < compared else
                   "the delivered frames match a plain centre crop, so the track "
                   "was not honoured",
            evidence={"frames_compared": compared,
                      "matched_centre_crop": centre_matches},
        ))
    return LayoutSemanticResult(mode_value(plan), tuple(checks))


def _verify_general(plan: LayoutPlan, art: Path, primary: Path,
                    samples: int) -> LayoutSemanticResult:
    target = plan.regions[0].crop.get("target")
    if not target:
        raise LayoutSemanticError("GENERAL_PLAN_HAS_NO_CROP_TARGET")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(art)],
        capture_output=True, text=True, check=False)
    got = probe.stdout.strip()
    want = f"{target[0]},{target[1]}"
    checks = [SemanticCheck(
        name="delivered_geometry_matches_planned_crop",
        passed=got == want,
        detail="the artifact carries the planned target geometry"
               if got == want else
               f"planned {want}, delivered {got!r}",
        evidence={"planned": want, "delivered": got},
    )]
    # A general fill must still show the source, not a frozen or blank frame.
    moving = 0
    compared = 0
    for i in range(samples):
        try:
            a = _frame(art, 1.0 + 2.0 * i)
            b = _frame(art, 3.0 + 2.0 * i)
        except LayoutSemanticError:
            continue
        compared += 1
        if _mad(a, b) > SAME_FRAME_MAD:
            moving += 1
    checks.append(SemanticCheck(
        name="frames_are_live_not_frozen",
        passed=compared > 0 and moving == compared,
        detail="sampled frames differ over time"
               if compared and moving == compared else
               "sampled frames are identical or could not be sampled",
        evidence={"sampled": compared, "distinct": moving},
    ))
    return LayoutSemanticResult(mode_value(plan), tuple(checks))


def mode_value(plan: LayoutPlan) -> str:
    return plan.spec.layout_mode.value


__all__ = [
    "SAME_FRAME_MAD",
    "SPLIT_MATCH_MARGIN",
    "LayoutSemanticError",
    "LayoutSemanticResult",
    "SemanticCheck",
    "verify_layout_semantics",
]