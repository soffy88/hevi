"""Turn a code-composed bed into a film-length BGM asset.

The engine masters its own pieces (dense styles -14 LUFS, gentle -16).  A
delivery bed is cut to the picture and brought to the S13/S22 target of
-14 LUFS / -1.5 dBTP here, with short fades so a cut never clicks.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any

from .engine import AnidoodleError
from .music import TEMPLATES, compose_bgm


def _ffmpeg(args: list[str], *, timeout: int = 600) -> None:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AnidoodleError(f"ffmpeg failed: {(result.stderr or '')[-800:]}")


def _bar_seconds(style: str) -> float:
    tpl = TEMPLATES.get(style)
    if not tpl:
        raise AnidoodleError(f"no validated music template for {style}")
    return 4 * 60.0 / float(tpl["bpm"])


def compose_for_duration(
    duration_s: float,
    *,
    style: str = "lofiElectronic",
    mood: str = "",
    key: str = "",
    seed: int = 29,
    target_lufs: float = -14.0,
) -> dict[str, Any]:
    """Compose a bed that covers ``duration_s`` and master it for delivery."""

    if duration_s <= 0 or duration_s > 900:
        raise AnidoodleError("duration_s must be between 0 and 900")
    bars = max(6, min(96, math.ceil((duration_s + 2.0) / _bar_seconds(style))))
    composed = compose_bgm(style=style, mood=mood, key=key, bars=bars, seed=seed, fmt="wav")
    source = Path(composed["path"])
    job = source.parent
    cut = job / "bed-cut.wav"
    fade_out = max(0.3, min(1.2, duration_s * 0.08))
    _ffmpeg(
        [
            "-i",
            str(source),
            "-t",
            f"{duration_s:.3f}",
            "-af",
            f"afade=t=in:st=0:d=0.2,afade=t=out:st={max(0.0, duration_s - fade_out):.3f}:d={fade_out:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(cut),
        ]
    )

    from hevi.qa.loudness import measure_loudness

    measured = measure_loudness(cut)
    normalized = False
    final = cut
    try:
        integrated = float(measured.get("input_i"))
    except TypeError, ValueError:
        integrated = None
    if integrated is not None and abs(integrated - target_lufs) > 0.5:
        mastered = job / "bed-master.wav"
        _ffmpeg(
            [
                "-i",
                str(cut),
                "-af",
                f"loudnorm=I={target_lufs:g}:TP=-1.5:LRA=11",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(mastered),
            ]
        )
        final = mastered
        normalized = True
        measured = measure_loudness(final)

    return {
        **composed,
        "path": str(final),
        "source_path": str(source),
        "duration_s": round(duration_s, 3),
        "bars": bars,
        "target_lufs": target_lufs,
        "loudness": measured,
        "normalized_to_target": normalized,
        "note": "code-composed bed, cut with fades and mastered for delivery; no recordings",
    }
