"""HEVI P5.1 — editorial reviewer calibration.

A reviewer that cannot be trusted with pairwise judgement must not be allowed to
promote candidates autonomously. Qualification is measured, not asserted:

* ``PAIRWISE_CALIBRATION_ACCURACY >= 0.80`` over at least ten known pairs
* ``POSITION_SWAP_CONSISTENCY >= 0.90``

and additionally the suite probes the specific failure modes that would quietly
corrupt promotion:

* can it see hard defects (blank/frozen stretches, fabricated interfaces)?
* does it prefer the *flashier* video when the calmer one is better (§76)?
* does it default to whichever candidate is second, i.e. assume the new one wins?

Failing any of these marks the reviewer ``NOT_QUALIFIED``, and the revision
session then refuses to promote autonomously.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.ops.p5_1_pairwise import (
    PairwiseOutcome,
    PairwiseUnavailable,
    run_bidirectional_pairwise,
)
from hevi.ops.p5_1_types import (
    RevisionCandidate,
    canonical_hash,
    video_file_hash,
)

MIN_KNOWN_PAIRS = 10
MIN_ACCURACY = 0.80
MIN_POSITION_SWAP_CONSISTENCY = 0.90


# ── Known pair definition ────────────────────────────────────────────────


@dataclass
class CalibrationPair:
    """A pair with a known-correct winner, used to qualify the reviewer."""

    pair_id: str
    better_path: str
    worse_path: str
    defect: str
    difficulty: str = "clear"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationResult:
    """Per-pair calibration outcome."""

    pair_id: str
    defect: str
    expected_winner: str = "BETTER"
    forward_picked: str = ""
    reversed_picked: str = ""
    correct: bool = False
    position_consistent: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationReport:
    """Aggregate reviewer qualification."""

    provider: str = ""
    model: str = ""
    pair_count: int = 0
    correct: int = 0
    accuracy: float = 0.0
    position_swaps_consistent: int = 0
    position_swap_consistency: float = 0.0
    hard_defect_detection: float = 0.0
    flashiness_preference: bool = False
    newer_default_bias: bool = False
    results: list[CalibrationResult] = field(default_factory=list)

    @property
    def failure_reasons(self) -> list[str]:
        """Derived from the measurements, so a report cannot claim more than it showed."""
        return _qualification_failures(self)

    @property
    def qualified(self) -> bool:
        return not self.failure_reasons

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["qualified"] = self.qualified
        d["failure_reasons"] = self.failure_reasons
        d["results"] = [r.to_dict() for r in self.results]
        return d


# ── Calibration set construction ─────────────────────────────────────────


def _ffmpeg(args: list[str], timeout: int = 300) -> bool:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _solid(path: Path, color: str, seconds: float) -> bool:
    return _ffmpeg([
        "-f", "lavfi", "-i", f"color=c={color}:s=480x270:d={seconds}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path),
    ])


def _phases(path: Path, colors: list[tuple[str, float]]) -> bool:
    """A clip made of ordered flat colour phases, with a real audio bed."""
    inputs: list[str] = []
    for color, seconds in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={color}:s=480x270:d={seconds}"]
    labels = "".join(f"[{i}:v]" for i in range(len(colors)))
    graph = f"{labels}concat=n={len(colors)}:v=1:a=0[v]"
    total = sum(s for _, s in colors)
    return _ffmpeg([
        *inputs,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex", graph, "-map", "[v]", "-map", f"{len(colors)}:a",
        "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-t", str(total), str(path),
    ])


def _with_black_gap(path: Path, colors: list[tuple[str, float]]) -> bool:
    """Same content but with a dead black stretch — a hard defect."""
    inputs: list[str] = []
    for color, seconds in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={color}:s=480x270:d={seconds}"]
    inputs += ["-f", "lavfi", "-i", "color=c=black:s=480x270:d=2"]
    labels = "".join(f"[{i}:v]" for i in range(len(colors) + 1))
    graph = f"{labels}concat=n={len(colors) + 1}:v=1:a=0[v]"
    return _ffmpeg([
        *inputs,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex", graph, "-map", "[v]", "-map", f"{len(colors) + 1}:a",
        "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path),
    ])


def _flashy(path: Path) -> bool:
    """A deliberately over-animated clip: many rapid hue shifts."""
    return _ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=25:duration=6",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", "hue=h=t*6,eq=saturation=1.6:contrast=1.2",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(path),
    ])


def build_calibration_set(workdir: Path) -> list[CalibrationPair]:
    """Build the known-pair calibration set from real rendered clips.

    Each pair is two genuinely different videos where the correct winner is
    known by construction, so reviewer accuracy is measured against reality
    rather than against another model's opinion.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    pairs: list[CalibrationPair] = []

    def add(pair_id: str, better: Path, worse: Path, defect: str, note: str) -> None:
        if better.is_file() and worse.is_file():
            pairs.append(
                CalibrationPair(
                    pair_id=pair_id,
                    better_path=str(better),
                    worse_path=str(worse),
                    defect=defect,
                    note=note,
                )
            )

    # 1-4: hard defect — a dead black stretch must always lose.
    for index, base_color in enumerate(
        ["teal", "olive", "navy", "maroon"], 1
    ):
        b_color = base_color
        good, bad = workdir / f"hd{index}_good.mp4", workdir / f"hd{index}_bad.mp4"
        if _phases(good, [(b_color, 2.0), ("white", 2.0)]) and _with_black_gap(
            bad, [(b_color, 2.0), ("white", 2.0)]
        ):
            add(f"HD{index}", good, bad, "DEAD_BLACK_STRETCH", "clean cut vs dead frames")

    # 5-7: flashiness — the calmer, better-paced clip must beat the noisy one.
    for index in (5, 6, 7):
        calm = workdir / f"fl{index}_good.mp4"
        noisy = workdir / f"fl{index}_bad.mp4"
        if _phases(calm, [("steelblue", 2.5), ("whitesmoke", 2.5), ("darkslategray", 2.0)]) and _flashy(noisy):
            add(f"FL{index}", calm, noisy, "EXCESSIVE_MOTION", "calm cut vs over-animated cut")

    # 8-10: information density — a readable two-beat cut beats a noisy one.
    for index in (8, 9, 10):
        good, bad = workdir / f"id{index}_good.mp4", workdir / f"id{index}_bad.mp4"
        if _phases(good, [("slategray", 3.0), ("gainsboro", 3.0)]) and _ffmpeg([
            "-f", "lavfi", "-i", "color=c=slategray:s=480x270:r=25:d=6",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf", "vibrance=1.8,noise=alls=24:allf=t",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(bad),
        ]):
            add(f"ID{index}", good, bad, "EXCESSIVE_INFORMATION_DENSITY", "readable vs noisy")

    # 11-12: visual stagnation — progression must beat an unchanging hold.
    for index in (11, 12):
        good, bad = workdir / f"vs{index}_good.mp4", workdir / f"vs{index}_bad.mp4"
        if _phases(good, [("seagreen", 1.5), ("goldenrod", 1.5), ("tomato", 1.5)]) and _solid(
            bad, "seagreen", 4.5
        ):
            add(f"VS{index}", good, bad, "VISUAL_STAGNATION", "progression vs unchanging hold")

    return pairs


# ── Running the calibration ──────────────────────────────────────────────


def _candidate(pair: CalibrationPair, path: str, candidate_id: str) -> RevisionCandidate:
    return RevisionCandidate(
        candidate_id=candidate_id,
        video_path=path,
        video_hash=video_file_hash(path),
        content_id=f"calib-{pair.pair_id}",
    )


async def run_calibration(
    pairs: list[CalibrationPair],
    *,
    workdir: Path,
    provider_id: str | None = None,
) -> CalibrationReport:
    """Run the calibration suite and decide reviewer qualification."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    report = CalibrationReport(pair_count=len(pairs))
    if not pairs:
        report.failure_reasons.append("NO_CALIBRATION_PAIRS")
        return report

    second_position_wins = 0
    decided = 0

    for pair in pairs:
        better = _candidate(pair, pair.better_path, f"{pair.pair_id}:BETTER")
        worse = _candidate(pair, pair.worse_path, f"{pair.pair_id}:WORSE")
        result = CalibrationResult(pair_id=pair.pair_id, defect=pair.defect)
        try:
            outcome: PairwiseOutcome = await run_bidirectional_pairwise(
                better,
                worse,
                workdir=workdir / pair.pair_id,
                content_id=better.content_id,
                provider_id=provider_id,
            )
        except PairwiseUnavailable as exc:
            result.note = f"UNAVAILABLE:{exc}"
            report.results.append(result)
            continue

        report.provider = report.provider or outcome.forward.provider
        report.model = report.model or outcome.forward.model

        result.forward_picked = outcome.forward.winner_candidate_id
        result.reversed_picked = outcome.reversed.winner_candidate_id
        expected = better.candidate_id
        result.correct = (
            result.forward_picked == expected and result.reversed_picked == expected
        )
        result.position_consistent = not outcome.position_bias_or_uncertain
        report.results.append(result)

        if outcome.forward.winner_candidate_id or outcome.reversed.winner_candidate_id:
            decided += 1
            # The *worse* clip is always in slot B forward / slot A reversed, so a
            # reviewer that simply always likes slot A would land on "worse" here.
            if outcome.forward.winner_candidate_id == worse.candidate_id:
                second_position_wins += 1
        if pair.defect in ("EXCESSIVE_MOTION", "EXCESSIVE_INFORMATION_DENSITY") and (
            result.forward_picked == worse.candidate_id
        ):
            report.flashiness_preference = True

    report.correct = sum(1 for r in report.results if r.correct)
    report.accuracy = report.correct / len(pairs) if pairs else 0.0
    consistent = sum(1 for r in report.results if r.position_consistent)
    report.position_swaps_consistent = consistent
    report.position_swap_consistency = consistent / len(pairs) if pairs else 0.0
    hard = [r for r in report.results if r.defect == "DEAD_BLACK_STRETCH"]
    report.hard_defect_detection = (
        sum(1 for r in hard if r.correct) / len(hard) if hard else 0.0
    )
    report.newer_default_bias = decided > 0 and (second_position_wins / decided) > 0.5

    return report


def _qualification_failures(report: CalibrationReport) -> list[str]:
    failures: list[str] = []
    if report.pair_count < MIN_KNOWN_PAIRS:
        failures.append(f"KNOWN_PAIR_COUNT_{report.pair_count}_BELOW_{MIN_KNOWN_PAIRS}")
    if report.accuracy < MIN_ACCURACY:
        failures.append(
            f"PAIRWISE_CALIBRATION_ACCURACY_{report.accuracy:.2f}_BELOW_{MIN_ACCURACY:.2f}"
        )
    if report.position_swap_consistency < MIN_POSITION_SWAP_CONSISTENCY:
        failures.append(
            f"POSITION_SWAP_CONSISTENCY_{report.position_swap_consistency:.2f}_BELOW_"
            f"{MIN_POSITION_SWAP_CONSISTENCY:.2f}"
        )
    if report.flashiness_preference:
        failures.append("PREFERS_FLASHIER_OVER_BETTER")
    if report.newer_default_bias:
        failures.append("DEFAULTS_TO_NEWER_CANDIDATE")
    return failures


def qualification_verdict(report: CalibrationReport) -> str:
    """The promotion-authority verdict for a calibrated reviewer."""
    return "QUALIFIED" if report.qualified else "NOT_QUALIFIED"


def calibration_fingerprint(pairs: list[CalibrationPair]) -> str:
    return canonical_hash(
        [
            {"pair_id": p.pair_id, "better": Path(p.better_path).name, "defect": p.defect}
            for p in pairs
        ]
    )


__all__ = [
    "MIN_ACCURACY",
    "MIN_KNOWN_PAIRS",
    "MIN_POSITION_SWAP_CONSISTENCY",
    "CalibrationPair",
    "CalibrationReport",
    "CalibrationResult",
    "build_calibration_set",
    "calibration_fingerprint",
    "qualification_verdict",
    "run_calibration",
]
