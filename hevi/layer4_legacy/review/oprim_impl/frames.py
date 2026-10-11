"""Frame sampling, pixel measurement and contact-sheet building (oprim layer).

Everything here is measured, never declared:

  - ``sample_frames``  really decodes N frames with ffmpeg
  - ``frame_stats``    computes mean/stdev luma from real pixels
  - ``frame_phash``    average-hash (deterministic, no ML)
  - ``interframe_delta`` mean absolute luma difference between consecutive frames
  - ``build_contact_sheet`` composes a real PNG grid from the sampled frames

Public functions are keyword-only (3O oprim boundary).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hevi.layer4_legacy.review.oprim_impl.contracts import FrameCheck
from hevi.layer4_legacy.review.oprim_impl.media import FFPROBE, MediaError, probe_media, run_ffmpeg

#: Luma thresholds (0..255, 8-bit grey).
BLACK_MEAN_LUMA = 16.0
FLAT_STDEV_LUMA = 3.0

#: Hash geometry for average-hash.
HASH_SIZE = 8


def sample_frames(
    *,
    path: str | Path,
    out_dir: str | Path,
    count: int = 4,
    scale_width: int = 0,
) -> list[Path]:
    """Decode ``count`` evenly-spaced frames (offset off the boundaries)."""
    src = Path(path)
    info = probe_media(src)
    if info.kind != "video":
        raise MediaError(f"cannot sample frames from non-video: {src}")
    if info.duration_s <= 0:
        raise MediaError(f"cannot sample frames from zero-duration video: {src}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for i in range(max(1, int(count))):
        t = info.duration_s * (i + 0.5) / max(1, int(count))
        dest = out / f"frame_{i:02d}_{t:06.2f}s.png"
        vf = f"scale={int(scale_width)}:-2" if scale_width else "null"
        run_ffmpeg(
            ["-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-vf", vf, str(dest)],
            timeout_s=300.0,
        )
        if not dest.is_file() or dest.stat().st_size == 0:
            raise MediaError(f"frame extraction produced nothing at {t:.3f}s ({src})")
        frames.append(dest)
    return frames


def dense_sample_frames(
    *,
    path: str | Path,
    out_dir: str | Path,
    fps: float = 2.0,
    scale_width: int = 128,
    max_frames: int = 48,
) -> list[Path]:
    """Decode frames at ``fps`` (capped by ``max_frames``) for slideshow risk.

    Unlike ``sample_frames`` (a few spot checks for black/broken), this samples
    densely enough that intra-segment stills and inter-segment cuts both get
    seen by the slideshow detector.  Returns a deterministic ordered list.
    """
    import math

    src = Path(path)
    info = probe_media(src)
    if info.kind != "video":
        raise MediaError(f"cannot dense-sample from non-video: {src}")
    if info.duration_s <= 0:
        raise MediaError(f"cannot dense-sample zero-duration video: {src}")
    out = Path(out_dir)
    if out.exists():
        for old in out.glob("d_*.png"):
            old.unlink()
    out.mkdir(parents=True, exist_ok=True)
    n = max(2, min(int(max_frames), max(2, int(math.ceil(info.duration_s * fps)))))
    pattern = out / f"d_%0{max(4, len(str(n)))}d.png"
    vf = f"scale={int(scale_width)}:-2,fps={fps}"
    run_ffmpeg(
        ["-y", "-i", str(src), "-vf", vf, "-vsync", "0", "-frames:v", str(n), str(pattern)],
        timeout_s=600.0,
    )
    frames = sorted(out.glob("d_*.png"))
    if not frames:
        raise MediaError(f"dense sampling produced no frames ({src})")
    return frames


def frame_stats(
    *,
    path: str | Path,
    index: int = 0,
    timestamp_s: float = 0.0,
    black_mean_luma: float = BLACK_MEAN_LUMA,
    flat_stdev_luma: float = FLAT_STDEV_LUMA,
) -> FrameCheck:
    """Measure one decoded frame: mean/stdev luma + black/flat/broken verdict.

    ``is_black``  — mean luma below threshold (a true black frame)
    ``is_flat``   — near-zero luma variance (frozen/blank/grey card frame)
    ``is_broken`` — the file could not be decoded at all (破图)
    """
    from PIL import Image, ImageStat

    dest = Path(path)
    try:
        with Image.open(dest) as im:
            grey = im.convert("L")
            stat = ImageStat.Stat(grey)
            mean = float(stat.mean[0])
            stdev = float(stat.stddev[0])
    except (OSError, ValueError) as exc:
        return FrameCheck(
            index=index,
            timestamp_s=round(float(timestamp_s), 3),
            path=str(dest),
            is_broken=True,
            notes=(f"undecodable frame: {type(exc).__name__}: {exc}",),
        )
    notes: list[str] = []
    is_black = mean < black_mean_luma
    if is_black:
        notes.append(f"black frame (mean luma {mean:.1f} < {black_mean_luma:.1f})")
    is_flat = stdev < flat_stdev_luma
    if is_flat:
        notes.append(f"flat frame (luma stdev {stdev:.2f} < {flat_stdev_luma:.2f})")
    return FrameCheck(
        index=index,
        timestamp_s=round(float(timestamp_s), 3),
        path=str(dest),
        mean_luma=round(mean, 3),
        stdev_luma=round(stdev, 3),
        is_black=is_black,
        is_flat=is_flat,
        is_broken=False,
        notes=tuple(notes),
    )


def frame_phash(*, path: str | Path, hash_size: int = HASH_SIZE) -> str:
    """average-hash of a frame: hex string of ``hash_size**2`` bits."""
    from PIL import Image

    with Image.open(path) as im:
        small = im.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
        px = list(small.tobytes())
    avg = sum(px) / len(px)
    bits = "".join("1" if p >= avg else "0" for p in px)
    return f"{int(bits, 2):0{hash_size * hash_size // 4}x}"


def hamming_distance(*, left: str, right: str) -> int:
    """Bit distance between two equal-length hex hashes."""
    if len(left) != len(right):
        return max(len(left), len(right)) * 4
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def interframe_delta(*, frames: list[Path], work_size: int = 64) -> list[float]:
    """Mean absolute luma delta (0..255) between consecutive frames."""
    import numpy as np
    from PIL import Image

    greys: list = []
    for frame in frames:
        with Image.open(frame) as im:
            arr = np.asarray(im.convert("L").resize((work_size, work_size)), dtype=np.float32)
        greys.append(arr)
    out: list[float] = []
    for i in range(1, len(greys)):
        out.append(round(float(np.abs(greys[i] - greys[i - 1]).mean()), 4))
    return out


def build_contact_sheet(
    *,
    frames: list[Path],
    output_path: str | Path,
    labels: tuple[str, ...] = (),
    columns: int = 0,
    cell_height: int = 180,
) -> dict[str, object]:
    """Compose a real PNG grid of the sampled frames. Returns measured geometry."""
    from PIL import Image, ImageDraw, ImageFont

    if not frames:
        raise MediaError("build_contact_sheet called with no frames")
    opened = [Image.open(f).convert("RGB") for f in frames]
    cols = int(columns) if columns > 0 else min(4, len(opened))
    rows = (len(opened) + cols - 1) // cols
    cw = max(img.width * cell_height // max(img.height, 1) for img in opened)
    label_h = 26 if labels else 0
    sheet = Image.new("RGB", (cw * cols, (cell_height + label_h) * rows), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    font = None
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            font = ImageFont.truetype(candidate, 16)
            break
    if font is None:
        font = ImageFont.load_default()
    for i, img in enumerate(opened):
        r, c = divmod(i, cols)
        x, y = c * cw, r * (cell_height + label_h)
        thumb = img.resize((cw, cell_height), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x, y))
        if labels and i < len(labels):
            draw.text((x + 6, y + cell_height + 4), str(labels[i]), fill=(235, 235, 240), font=font)
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest)
    for img in opened:
        img.close()
    return {
        "path": str(dest),
        "width": sheet.width,
        "height": sheet.height,
        "frames": len(frames),
        "columns": cols,
        "rows": rows,
    }


def probe_frame_count(*, path: str | Path) -> int:
    """Real decoded frame count (ffprobe -count_frames), 0 if unreadable."""
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    raw = (proc.stdout or "").strip().splitlines()
    return int(raw[0]) if raw and raw[0].isdigit() else 0


__all__ = [
    "BLACK_MEAN_LUMA",
    "FLAT_STDEV_LUMA",
    "HASH_SIZE",
    "build_contact_sheet",
    "frame_phash",
    "frame_stats",
    "hamming_distance",
    "interframe_delta",
    "probe_frame_count",
    "sample_frames",
]
