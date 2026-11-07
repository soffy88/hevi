"""Image-level first/last-frame consistency check (post-generation QA).

This module answers one question the beat-schema compiler cannot: do
the generated clip's actual first and last frames look like the
designed first and last frames? The compiler (``story.prompt_compiler``)
checks the schema-level state chain and the ``start_frame`` marker;
this module checks pixels.

Report-only by design
----------------------
``check_clip_endpoints`` never raises on a similarity breach and never
blocks a clip. Thresholds for "close enough" are uncalibrated until
pilot data exists (the CozyClay pilot's designed endpoints plus
generated clips); blocking on an uncalibrated threshold would repeat
the old failure in reverse -- false blocks instead of false passes.
Callers may pass ``thresholds`` to get informational ``meets_threshold``
flags, but the verdict stays ``"report_only"`` until a calibration
round writes thresholds into this module's documentation with
measured numbers behind them. Threshold calibration is a pilot-data
follow-up, not a gap in this mechanism.

Metrics
-------
* ``mad``: mean absolute pixel difference on 256x144 grayscale,
  0-255 scale. Lower means more similar. 0 means identical pixels.
* ``ssim``: structural similarity in [0, 1] from scikit-image when
  available (``None`` otherwise). Higher means more similar.
  1.0 means identical structure.

Baseline caveat
--------------
A generated clip's first frame compared against its *reference still*
(the aspirational image the clip was prompted from) is a different
measurement from a designed endpoint compared against a generated
endpoint. Reference stills are not designed endpoints: the model is
expected to move away from them. A reference-still baseline is
therefore a distribution to learn from, not a pass bar. Do not turn
baseline numbers into thresholds without designed-endpoint data.

Dependencies: ffmpeg on PATH (frame extraction), Pillow and numpy
(pixel math), scikit-image optional (SSIM only). No new heavy
dependency is introduced for this module.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_SIZE: tuple[int, int] = (256, 144)


def _load_gray(path: str | Path, size: tuple[int, int] = DEFAULT_SIZE) -> Any:
    """Load an image as a float64 grayscale array at ``size``."""
    from PIL import Image
    import numpy as np

    img = Image.open(str(path)).convert("L").resize(size)
    return np.asarray(img, dtype=np.float64)


def frame_similarity(
    a_path: str | Path,
    b_path: str | Path,
    size: tuple[int, int] = DEFAULT_SIZE,
) -> dict[str, Any]:
    """Similarity between two images: ``{"mad": float, "ssim": float | None}``.

    Raises ``FileNotFoundError`` when either path is missing, so a
    typo'd design frame fails loudly instead of scoring zero.
    """
    import numpy as np

    a_path, b_path = Path(a_path), Path(b_path)
    if not a_path.exists():
        raise FileNotFoundError(f"frame_consistency: missing image {a_path}")
    if not b_path.exists():
        raise FileNotFoundError(f"frame_consistency: missing image {b_path}")
    a = _load_gray(a_path, size)
    b = _load_gray(b_path, size)
    mad = float(np.mean(np.abs(a - b)))
    ssim: float | None = None
    try:
        from skimage.metrics import structural_similarity

        ssim = float(structural_similarity(a, b, data_range=255))
    except Exception:
        ssim = None
    return {"mad": mad, "ssim": ssim}


def _clip_duration_s(clip_path: Path) -> float | None:
    """Clip duration in seconds via ffprobe, or None when unavailable."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(clip_path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip().splitlines()[0])
    except Exception:
        return None


def _extract_last_frame(ffmpeg: str, clip_path: Path, last_png: Path) -> None:
    """Write the clip's last frame to ``last_png``.

    Attempt 1 selects the exact last frame by index. Attempt 2 seeks
    to 0.1s before the end (``-sseof`` is unreliable on this ffmpeg
    build for mp4: it yields zero frames). Raises ``RuntimeError``
    only when both attempts produce no file.
    """
    attempt = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(clip_path),
         "-vf", "select='eq(n\\,nb_frames-1)'",
         "-frames:v", "1", str(last_png)],
        capture_output=True, text=True,
    )
    if attempt.returncode == 0 and last_png.exists():
        return
    duration = _clip_duration_s(clip_path)
    if duration is not None and duration > 0.2:
        attempt = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-ss", str(duration - 0.1),
             "-i", str(clip_path), "-frames:v", "1", str(last_png)],
            capture_output=True, text=True,
        )
        if attempt.returncode == 0 and last_png.exists():
            return
    raise RuntimeError(
        "frame_consistency: last-frame extraction failed "
        f"(select filter: {attempt.stderr.strip()})"
    )


def extract_endpoint_frames(
    clip_path: str | Path, out_dir: str | Path
) -> tuple[Path, Path]:
    """Extract a clip's first frame (t=0) and last frame.

    Returns ``(first_png, last_png)``. Raises ``RuntimeError`` when
    ffmpeg is missing or extraction fails.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("frame_consistency: ffmpeg not found on PATH")
    clip_path = Path(clip_path)
    if not clip_path.exists():
        raise FileNotFoundError(f"frame_consistency: missing clip {clip_path}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    first_png = out / "clip_first.png"
    last_png = out / "clip_last.png"
    first = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(clip_path),
         "-frames:v", "1", str(first_png)],
        capture_output=True, text=True,
    )
    if first.returncode != 0 or not first_png.exists():
        raise RuntimeError(
            "frame_consistency: first-frame extraction failed: "
            f"{first.stderr.strip()}"
        )
    _extract_last_frame(ffmpeg, clip_path, last_png)
    return first_png, last_png


def check_clip_endpoints(
    design_first: str | Path,
    design_last: str | Path,
    clip_path: str | Path,
    thresholds: dict[str, Any] | None = None,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Report-only endpoint check for one generated clip.

    ``thresholds`` (optional, informational only) looks like
    ``{"mad_max": 20.0, "ssim_min": 0.5}``. ``meets_threshold`` is
    ``True``/``False`` per end when thresholds are given, else
    ``None``. The verdict is always ``"report_only"``: this function
    never raises on a similarity breach and never blocks a clip.
    """
    tmp = Path(work_dir) if work_dir is not None else Path(
        tempfile.mkdtemp(prefix="frame_consistency_")
    )
    first_png, last_png = extract_endpoint_frames(clip_path, tmp)
    first = frame_similarity(design_first, first_png)
    last = frame_similarity(design_last, last_png)

    def _meets(scores: dict[str, Any]) -> bool | None:
        if not thresholds:
            return None
        mad_max = thresholds.get("mad_max")
        ssim_min = thresholds.get("ssim_min")
        ok = True
        if mad_max is not None and scores["mad"] > float(mad_max):
            ok = False
        if (
            ssim_min is not None
            and scores["ssim"] is not None
            and scores["ssim"] < float(ssim_min)
        ):
            ok = False
        return ok

    return {
        "verdict": "report_only",
        "clip": str(clip_path),
        "design_first": str(design_first),
        "design_last": str(design_last),
        "clip_first_frame": str(first_png),
        "clip_last_frame": str(last_png),
        "first": first,
        "last": last,
        "thresholds": thresholds,
        "meets_threshold": {"first": _meets(first), "last": _meets(last)},
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: check one clip's endpoints against designed frames."""
    parser = argparse.ArgumentParser(
        description="Report-only first/last-frame consistency check"
    )
    parser.add_argument("design_first", help="designed first-frame image")
    parser.add_argument("design_last", help="designed last-frame image")
    parser.add_argument("clip", help="generated clip (mp4)")
    parser.add_argument("--work-dir", default=None,
                        help="directory for extracted frames")
    parser.add_argument("--threshold-mad", type=float, default=None,
                        help="informational MAD ceiling (lower is more similar)")
    parser.add_argument("--threshold-ssim", type=float, default=None,
                        help="informational SSIM floor (higher is more similar)")
    args = parser.parse_args(argv)
    thresholds: dict[str, Any] | None = None
    if args.threshold_mad is not None or args.threshold_ssim is not None:
        thresholds = {}
        if args.threshold_mad is not None:
            thresholds["mad_max"] = args.threshold_mad
        if args.threshold_ssim is not None:
            thresholds["ssim_min"] = args.threshold_ssim
    report = check_clip_endpoints(
        args.design_first, args.design_last, args.clip,
        thresholds=thresholds, work_dir=args.work_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
