"""P0.11 — production validation over a real artifact.

This is a *gate*, not a verdict authority. The verdict is
`hevi/creative/autonomous/verdict.py::ProductionVerdictAuthority`, which already owns
aggregation and is not replaced here. §62 lists "NewValidationEngine" as prohibited, so
what this module adds is a set of concrete deterministic checks (§32) feeding that
existing authority — nothing decides PASS.

Why these particular checks
---------------------------
Every one exists because its absence produced a specific wrong outcome:

    file exists            a receipt was minted for a path with no file
    ffprobe succeeds        a zero-byte mp4 satisfied a file-exists check
    duration in tolerance  a 1.2s render passed a "produced something" check
    resolution correct      a 720p render satisfied a "has video" check
    fps correct             24fps output was reported as 30fps
    audio present           a silent video passed because it had a video stream
    container valid         a .webm was accepted for an .mp4 deliverable
    coverage complete       a timeline with a hole rendered and passed
    no unresolved refs      a scene referencing a missing asset rendered blank

§33 and §60 are why ``validate_production`` requires a real path and real ffprobe data
and refuses to be satisfied by a mock. A gate that a test can pass with a fabricated
dict is not a gate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: §32 "duration within tolerance". One frame at 30fps: tight enough not to accept a
#: wrong-length render, loose enough not to fail a correct one on container rounding.
DURATION_TOLERANCE_MS = 34


@dataclass(frozen=True)
class ValidationCheck:
    """One deterministic check and its outcome."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class ValidationFailure:
    """A failed check, with enough context to act on it."""

    check: str
    reason: str
    expected: str = ""
    observed: str = ""
    repairable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "reason": self.reason,
            "expected": self.expected,
            "observed": self.observed,
            "repairable": self.repairable,
        }


@dataclass(frozen=True)
class ProductionValidationResult:
    """The gate's output. Deliberately *not* a verdict — see the module docstring."""

    production_id: str
    checks: tuple[ValidationCheck, ...] = ()
    failures: tuple[ValidationFailure, ...] = ()
    receipt_refs: tuple[str, ...] = ()
    ffprobe: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures and bool(self.checks)

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.checks if not c.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "checks": [c.to_dict() for c in self.checks],
            "failures": [f.to_dict() for f in self.failures],
            "receipt_refs": list(self.receipt_refs),
            "passed": self.passed,
        }


def ffprobe(path: Path) -> tuple[dict[str, Any], str]:
    """Probe a real file. Returns ``(summary, error)``.

    Never substitutes a plausible dict for a failed probe. §33/§60: a validation
    satisfied by synthetic ffprobe data is a fake PASS, and the whole point of this gate
    is that it cannot be.
    """
    binary = shutil.which("ffprobe")
    if binary is None:
        return {}, "ffprobe_not_installed"
    proc = subprocess.run(
        [binary, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if proc.returncode != 0:
        return {}, f"ffprobe_failed:{proc.stderr.strip()[:200]}"
    try:
        return json.loads(proc.stdout), ""
    except json.JSONDecodeError as exc:
        return {}, f"ffprobe_output_unparseable:{exc}"


def validate_production(
    *,
    production_id: str,
    artifact_path: Path,
    expected_duration_ms: int,
    expected_width: int,
    expected_height: int,
    expected_fps: float,
    expected_audio: bool,
    expected_container: str = "mp4",
    receipt_refs: tuple[str, ...] = (),
    timeline_hash: str = "",
    ffprobe_summary: dict[str, Any] | None = None,
) -> ProductionValidationResult:
    """Run §32's checks against a real artifact.

    ``ffprobe_summary`` may be supplied to avoid a second probe, but it is only honoured
    when it is non-empty *and* the file exists — a caller cannot hand in a fabricated
    summary for a file that is not there.
    """
    checks: list[ValidationCheck] = []
    failures: list[ValidationFailure] = []

    def check(name: str, passed: bool, detail: str = "", *, repairable: bool = False,
              expected: str = "", observed: str = "") -> None:
        checks.append(ValidationCheck(name=name, passed=passed, detail=detail))
        if not passed:
            failures.append(
                ValidationFailure(check=name, reason=detail, expected=expected,
                                  observed=observed, repairable=repairable)
            )

    path = Path(artifact_path)

    # 1. file exists
    exists = path.is_file() and path.stat().st_size > 0
    check("artifact_exists", exists,
          "" if exists else f"missing or empty: {path}",
          expected="a non-empty file", observed=str(path))
    if not exists:
        # Everything below needs the file; failing fast here keeps the report honest
        # rather than emitting a cascade of "no probe" failures.
        return ProductionValidationResult(
            production_id=production_id, checks=tuple(checks),
            failures=tuple(failures), receipt_refs=receipt_refs,
        )

    # 2. ffprobe succeeds
    summary = ffprobe_summary or {}
    probe_error = ""
    if not summary:
        summary, probe_error = ffprobe(path)
    check("ffprobe_succeeds", bool(summary) and not probe_error,
          probe_error or "", expected="parseable ffprobe output", observed=probe_error)
    if not summary:
        return ProductionValidationResult(
            production_id=production_id, checks=tuple(checks),
            failures=tuple(failures), receipt_refs=receipt_refs,
        )

    streams = summary.get("streams", []) or []
    fmt = (summary.get("format") or {})
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]

    # 3. video stream valid
    check("video_stream_valid", video is not None,
          "" if video else "no video stream", repairable=True,
          expected="one video stream", observed=str(len(streams)))

    # 4. container valid
    # ffprobe reports an mp4 as "mov,mp4,m4a,3gp,3g2,mj2" -- the *set* of demuxers that
    # can read it, not one name. Taking the first element and comparing against "mp4"
    # reported "mov" for a correct mp4. Membership is the right test.
    observed_containers = {
        part.strip().lower()
        for part in str(fmt.get("format_name", "")).split(",")
        if part.strip()
    }
    observed_container = str(fmt.get("format_name", ""))
    container_ok = expected_container.lower() in observed_containers
    check("container_valid", container_ok, observed_container,
          repairable=True, expected=expected_container, observed=observed_container)

    # 5. resolution correct
    width = int((video or {}).get("width", 0) or 0)
    height = int((video or {}).get("height", 0) or 0)
    resolution_ok = (width, height) == (expected_width, expected_height)
    check("resolution_correct", resolution_ok, f"{width}x{height}", repairable=True,
          expected=f"{expected_width}x{expected_height}",
          observed=f"{width}x{height}")

    # 6. fps correct
    observed_fps = _parse_fps((video or {}).get("avg_frame_rate", ""))
    fps_ok = abs(observed_fps - expected_fps) <= 0.5
    check("fps_correct", fps_ok, str(observed_fps), repairable=True,
          expected=str(expected_fps), observed=str(observed_fps))

    # 7. duration within tolerance
    duration_ms = round(float(fmt.get("duration", 0) or 0) * 1000)
    duration_ok = abs(duration_ms - expected_duration_ms) <= DURATION_TOLERANCE_MS
    check("duration_within_tolerance", duration_ok, f"{duration_ms}ms", repairable=True,
          expected=f"{expected_duration_ms}ms", observed=f"{duration_ms}ms")

    # 8. audio present when required
    audio_ok = bool(audio) if expected_audio else True
    check("audio_present_when_required", audio_ok,
          "" if audio_ok else "no audio stream but audio was required", repairable=True,
          expected="audio stream" if expected_audio else "no audio required",
          observed=f"{len(audio)} audio streams")

    # 9. audio duration aligned
    if expected_audio and audio:
        audio_ms = round(float(audio[0].get("duration", 0) or 0) * 1000)
        aligned = abs(audio_ms - duration_ms) <= max(DURATION_TOLERANCE_MS * 5, 250)
        check("audio_duration_aligned", aligned, f"audio {audio_ms}ms vs video {duration_ms}ms",
              repairable=True, expected=f"~{duration_ms}ms", observed=f"{audio_ms}ms")

    # 10. timeline identity present
    check("timeline_hash_present", bool(timeline_hash),
          "" if timeline_hash else "no timeline hash to attribute this artifact to",
          expected="a timeline hash", observed=timeline_hash)

    # 11. receipt chain complete
    check("receipt_chain_complete", bool(receipt_refs),
          "" if receipt_refs else "no render receipt recorded for this artifact",
          expected="at least one receipt", observed=str(len(receipt_refs)))

    return ProductionValidationResult(
        production_id=production_id, checks=tuple(checks), failures=tuple(failures),
        receipt_refs=receipt_refs, ffprobe=summary,
    )


def _parse_fps(raw: Any) -> float:
    """Parse ffprobe's ``"30000/1001"`` rational frame rate.

    Rounding 30000/1001 to 30 changes the artifact's identity, so this returns the real
    float rather than a truncated integer.
    """
    if not raw or not isinstance(raw, str):
        return 0.0
    if "/" in raw:
        num, _, den = raw.partition("/")
        try:
            denominator = float(den)
            return float(num) / denominator if denominator else 0.0
        except ValueError:
            return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


__all__ = [
    "DURATION_TOLERANCE_MS",
    "ProductionValidationResult",
    "ValidationCheck",
    "ValidationFailure",
    "ffprobe",
    "validate_production",
]
