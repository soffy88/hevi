"""Subtitle (SRT) parsing and out-of-bounds checking (oprim, pure-ish).

"字幕越界" means: a cue window falls outside the video, or outside the safe
margin the delivery target requires, or is so short it cannot be read.  All
three are measured against the real probed duration — never assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hevi.layer4_legacy.review.oprim_impl.media import MediaError, probe_media

_TS = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
_CUE_RE = re.compile(rf"{_TS}\s*-->\s*{_TS}")


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


@dataclass(frozen=True)
class Cue:
    index: int
    start_s: float
    end_s: float
    text: str = ""

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "duration_s": round(self.duration_s, 3),
            "text": self.text,
        }


def parse_srt(*, path: str | Path) -> list[Cue]:
    """Parse an SRT file into cues. Raises MediaError if unreadable."""
    dest = Path(path)
    if not dest.is_file():
        raise MediaError(f"subtitle file not found: {dest}")
    try:
        raw = dest.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise MediaError(f"cannot read subtitle file {dest}: {exc}") from exc
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    for i, block in enumerate(blocks):
        m = _CUE_RE.search(block)
        if not m:
            continue
        start = _to_seconds(*m.group(1, 2, 3, 4))
        end = _to_seconds(*m.group(5, 6, 7, 8))
        text = "\n".join(
            line.strip() for line in block.splitlines()[1:] if line.strip() and "-->" not in line
        )
        cues.append(Cue(index=i, start_s=start, end_s=end, text=text))
    return cues


def out_of_bounds(
    *,
    cues: list[Cue],
    duration_s: float,
    safe_margin_s: float = 0.0,
    min_cue_s: float = 0.4,
) -> dict[str, object]:
    """Count cues that break the three measurable bounds.

    Returns absolute counts so the caller can report honestly; ``duration_s``
    must be a real probe (0 means "unknown", in which case bounds are skipped
    and reported as unmeasured rather than as zero violations).
    """
    if not cues:
        return {
            "cues": 0,
            "past_end": 0,
            "before_start": 0,
            "too_short": 0,
            "overlapping": 0,
            "violations": [],
        }
    violations: list[dict[str, object]] = []
    past_end = before_start = too_short = overlapping = 0
    measured_bounds = duration_s > 0
    for cue in cues:
        if measured_bounds and cue.end_s > duration_s + 0.001:
            past_end += 1
            violations.append(
                {"index": cue.index, "kind": "past_end", "end_s": round(cue.end_s, 3)}
            )
        if cue.start_s < -0.001 or (
            measured_bounds and safe_margin_s and cue.start_s < safe_margin_s - 0.001
        ):
            before_start += 1
            violations.append(
                {"index": cue.index, "kind": "before_safe_start", "start_s": round(cue.start_s, 3)}
            )
        if cue.duration_s < min_cue_s:
            too_short += 1
            violations.append(
                {"index": cue.index, "kind": "too_short", "duration_s": round(cue.duration_s, 3)}
            )
    for a, b in zip(cues, cues[1:]):
        if b.start_s < a.end_s - 0.001:
            overlapping += 1
            violations.append({"index": b.index, "kind": "overlap_previous"})
    return {
        "cues": len(cues),
        "past_end": past_end,
        "before_start": before_start,
        "too_short": too_short,
        "overlapping": overlapping,
        "bounds_measured": measured_bounds,
        "violations": violations[:20],
    }


def cue_coverage(*, cues: list[Cue], duration_s: float) -> float | None:
    """Fraction of runtime covered by at least one cue. None if unmeasurable."""
    if not cues or duration_s <= 0:
        return None
    covered = sum(min(cue.duration_s, duration_s) for cue in cues)
    return round(min(1.0, covered / duration_s), 4)


def subtitle_bounds_for_video(
    *,
    video_path: str | Path,
    subtitle_path: str | Path,
    safe_margin_s: float = 0.0,
    min_cue_s: float = 0.4,
) -> dict[str, object]:
    """Probe the video, parse the SRT, and measure the bounds in one call."""
    info = probe_media(video_path)
    cues = parse_srt(path=subtitle_path)
    bounds = out_of_bounds(
        cues=cues,
        duration_s=info.duration_s,
        safe_margin_s=safe_margin_s,
        min_cue_s=min_cue_s,
    )
    bounds["coverage"] = cue_coverage(cues=cues, duration_s=info.duration_s)
    bounds["subtitle_path"] = str(subtitle_path)
    bounds["video_duration_s"] = info.duration_s
    return bounds


__all__ = [
    "Cue",
    "cue_coverage",
    "out_of_bounds",
    "parse_srt",
    "subtitle_bounds_for_video",
]
