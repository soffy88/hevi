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

#: Spatial quality thresholds for 破图/花屏 detection.
NOISE_LOCAL_DIFF_FLOOR = 30.0  # local_diff above this suggests noise
#: Blockiness: ratio of 16px/8px grid boundary-pair diff to interior diff.
#: Real macroblock artefacts produce a ratio ≫ 1; clean frames are near 1.
#:
#: Basis (measured, see OMQUALITY_DONE.md r5): on 4-point full-resolution
#: samples the worst normal clip peaks at 1.449 (hf_v6-cinematic) while the
#: mildest bad clip (libx264 -qp 51) starts at 1.828 — a 1.70 floor leaves
#: ~0.25 margin below and ~0.13 above, wider than the previous 1.8 (0.03).
#: Blockiness is only evaluated on full-resolution spot frames: at the small
#: dense-scan width it is dominated by scaling artefacts (a normal chalkboard
#: clip reaches 4.45), so it must not gate the whole-clip scan.
BLOCKY_RATIO_FLOOR = 1.70
#: Kept for backwards-compatibility with imports/tests; no longer used by
#: frame_stats (the ratio-based detector supersedes the absolute threshold).
BLOCKINESS_FLOOR = 40.0
EDGE_DENSITY_FLOOR = 0.50  # fraction of strong edges (noise has ~1.0)
MIN_SPATIAL_VARIATION = 5.0  # minimum stdev for non-flat frame

#: Region-flat detection (fine-grained, non-quadrant-aligned colour blocks).
#: A solid-colour corruption block makes every *line* (row or column) inside it
#: near-uniform.  ``REGION_UNIFORM_STDEV`` is the per-line luma stdev below
#: which a line counts as uniform; ``REGION_MIN_FRAC`` is the minimum share of
#: the frame the contiguous uniform run must cover; ``REGION_MIN_STEP`` is the
#: minimum luma difference between the run and its immediate neighbours.
#:
#: Basis (measured): a real half-screen / third-screen grey bar has per-line
#: stdev ≈ 0.02–0.03 and a boundary step of 27–59 luma, while normal "flat"
#: backgrounds (chalkboard/title cards) keep per-line stdev ≈ 1.8–2.5 and a
#: step of 0.1–2 — so 1.0 / 0.15 / 20 separates them with >2x margin.
REGION_UNIFORM_STDEV = 1.0
REGION_MIN_FRAC = 0.15
REGION_MIN_STEP = 20.0

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
    max_frames: int = 0,
    flags: str = "neighbor",
) -> list[Path]:
    """Decode frames at ``fps`` over the WHOLE clip for dense defect scanning.

    Unlike ``sample_frames`` (a few spot checks for black/broken), this decodes
    the entire runtime so an intra-segment still, a local glitch, or a
    non-quadrant colour block anywhere in the clip is seen.  ``max_frames`` is a
    safety cap only; the default ``0`` means "no cap" so the scan never silently
    truncates a long clip to its first N seconds (the r5 defect: ``-frames:v 48``
    at 2 fps covered only the first 24 s).

    ``flags`` defaults to ``neighbor``: nearest-neighbour downscaling keeps the
    per-pixel high-frequency energy that ``bicubic`` averages away, so a noise
    glitch stays detectable even at a small decode width.
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
    wanted = max(2, int(math.ceil(info.duration_s * fps)))
    n = wanted if int(max_frames) <= 0 else min(int(max_frames), wanted)
    pattern = out / f"d_%0{max(4, len(str(n)))}d.png"
    vf = f"scale={int(scale_width)}:-2:flags={flags},fps={fps}"
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

    # Chroma / colour anomaly detection (green screen, solid colour flood).
    # A decoded-failure green screen has Y=0 U=0 V=0 → RGB (0,135,0) i.e.
    # G≈4×R and G≈4×B with R≈B≈0; we detect via RGB channel stats when
    # the frame is also flat.
    is_color_anomaly = False
    try:
        from PIL import Image as _Image

        with _Image.open(dest) as _im:
            _rgb = _im.convert("RGB")
            _r, _g, _b = _rgb.split()
            _r_mean = float(ImageStat.Stat(_r).mean[0])
            _g_mean = float(ImageStat.Stat(_g).mean[0])
            _b_mean = float(ImageStat.Stat(_b).mean[0])
            # Green-screen: G dominates with R/B near zero and frame is flat.
            if _r_mean < 30 and _b_mean < 30 and _g_mean > 50 and is_flat:
                is_color_anomaly = True
                notes.append(
                    f"color anomaly: green screen (R={_r_mean:.0f}, G={_g_mean:.0f}, B={_b_mean:.0f})"
                )
    except OSError, ValueError:
        pass

    # --- spatial quality: detect noise / macroblock / screen corruption ---
    import numpy as np

    arr = np.asarray(grey, dtype=np.float64)
    h, w = arr.shape
    # Gradient magnitudes (mean absolute first difference along each axis)
    gx = np.abs(arr[:, 1:] - arr[:, :-1])  # (h, w-1)
    gy = np.abs(arr[1:, :] - arr[:-1, :])  # (h-1, w)
    gx_mean = float(gx.mean())
    gy_mean = float(gy.mean())
    # Edge density: fraction of pixels with strong local gradient (>15/255)
    edge_h = float((gx > 15.0).mean())
    edge_v = float((gy > 15.0).mean())
    # Local 8-neighbour difference (high-frequency energy proxy)
    padded = np.pad(arr, 1, mode="edge")
    local_diffs: list[float] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            local_diffs.append(
                float(np.abs(padded[1 + dy : h + 1 + dy, 1 + dx : w + 1 + dx] - arr).mean())
            )
    local_diff = sum(local_diffs) / float(len(local_diffs))

    # Blockiness: ratio of boundary-pair diff to interior diff at 16px and 8px grids.
    # A value ≫ 1 indicates periodic quantisation boundaries (real macroblock artefacts);
    # values near 1 indicate ordinary image content regardless of texture density.
    def _bnd_interior_ratio(a: "np.ndarray", size: int) -> tuple[float, float]:
        h_, w_ = a.shape
        b_sum = 0.0
        i_sum = 0.0
        cols_b = np.arange(size - 1, w_ - 1, size)
        cols_i = cols_b + 1
        if len(cols_b) and len(cols_i):
            b_sum += float(np.abs(a[:, cols_b] - a[:, cols_i]).mean())
        rows_b = np.arange(size - 1, h_ - 1, size)
        rows_i = rows_b + 1
        if len(rows_b) and len(rows_i):
            b_sum += float(np.abs(a[rows_b, :] - a[rows_i, :]).mean())
        mask_h = np.ones(w_, dtype=bool)
        mask_h[cols_b] = False
        mask_h[cols_i] = False
        mask_v = np.ones(h_, dtype=bool)
        mask_v[rows_b] = False
        mask_v[rows_i] = False
        dh = np.abs(np.diff(a[:, mask_h], axis=1))
        dv = np.abs(np.diff(a[mask_v, :], axis=0))
        if dh.size:
            i_sum += float(dh.mean())
        if dv.size:
            i_sum += float(dv.mean())
        return b_sum, i_sum

    b16, i16 = _bnd_interior_ratio(arr, 16)
    b8, i8 = _bnd_interior_ratio(arr, 8)
    ratio16 = b16 / max(i16, 1e-9)
    ratio8 = b8 / max(i8, 1e-9)
    blockiness = round(max(ratio16, ratio8), 3)
    is_blocky = bool(blockiness >= BLOCKY_RATIO_FLOOR)

    # Noise: high local-diff AND high edge density together.
    is_noise = bool(
        local_diff > NOISE_LOCAL_DIFF_FLOOR and (edge_h + edge_v) / 2.0 > EDGE_DENSITY_FLOOR
    )
    if is_noise:
        notes.append(
            f"noise-like frame (local_diff {local_diff:.1f} > {NOISE_LOCAL_DIFF_FLOOR:.0f}, edge_density {(edge_h + edge_v) / 2.0:.2f})"
        )
    if is_blocky:
        notes.append(
            f"blocky frame (boundary/interior ratio {blockiness:.2f} ≥ {BLOCKY_RATIO_FLOOR:.1f})"
        )

    # Region-based flatness: a contiguous solid-colour corruption block (grey
    # bar, colour flood) makes every *line* (row or column) inside it uniform,
    # and its luma steps sharply away from the neighbouring content.  Scanning
    # whole rows/columns — not a 2x2 quadrant grid — catches non-quadrant-aligned
    # blocks (e.g. a right-third-width bar) while a normal large flat background
    # (title card, chalkboard) is rejected because its lines keep real texture
    # (per-line stdev ≫ REGION_UNIFORM_STDEV) and no colour step.
    is_region_flat = False
    if not is_flat:
        for _axis, _name in ((0, "row"), (1, "col")):
            _red = 1 if _axis == 0 else 0
            _line_std = arr.std(axis=_red)
            _line_mean = arr.mean(axis=_red)
            _n = int(_line_std.size)
            _flat = _line_std < REGION_UNIFORM_STDEV
            _best = _cur = _bs = _cs = 0
            for _i, _f in enumerate(_flat):
                if _f:
                    if _cur == 0:
                        _cs = _i
                    _cur += 1
                    if _cur > _best:
                        _best, _bs = _cur, _cs
                else:
                    _cur = 0
            if _best == 0:
                continue
            _frac = _best / _n
            if _frac < REGION_MIN_FRAC:
                continue
            _k = 3
            _pre = _line_mean[max(0, _bs - _k) : _bs]
            _post = _line_mean[_bs + _best : _bs + _best + _k]
            _run_mean = float(_line_mean[_bs : _bs + _best].mean())
            _step = max(
                abs(_run_mean - float(_pre.mean())) if _pre.size else 0.0,
                abs(_run_mean - float(_post.mean())) if _post.size else 0.0,
            )
            if _step >= REGION_MIN_STEP:
                is_region_flat = True
                notes.append(
                    f"region flat: {_name} run {_best}/{_n} ({_frac:.0%}) uniform "
                    f"(per-line stdev<{REGION_UNIFORM_STDEV:.1f}), step {_step:.0f} luma"
                )
                break

    return FrameCheck(
        index=index,
        timestamp_s=round(float(timestamp_s), 3),
        path=str(dest),
        mean_luma=round(mean, 3),
        stdev_luma=round(stdev, 3),
        is_black=is_black,
        is_flat=is_flat,
        is_broken=False,
        gradient_x=round(gx_mean, 3),
        gradient_y=round(gy_mean, 3),
        edge_density_h=round(edge_h, 4),
        edge_density_v=round(edge_v, 4),
        local_diff=round(local_diff, 3),
        blockiness=blockiness,
        is_noise=is_noise,
        is_blocky=is_blocky,
        is_color_anomaly=is_color_anomaly,
        is_region_flat=is_region_flat,
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
    "NOISE_LOCAL_DIFF_FLOOR",
    "BLOCKY_RATIO_FLOOR",
    "BLOCKINESS_FLOOR",
    "EDGE_DENSITY_FLOOR",
    "MIN_SPATIAL_VARIATION",
    "FLAT_STDEV_LUMA",
    "HASH_SIZE",
    "REGION_UNIFORM_STDEV",
    "REGION_MIN_FRAC",
    "REGION_MIN_STEP",
    "build_contact_sheet",
    "dense_sample_frames",
    "frame_phash",
    "frame_stats",
    "hamming_distance",
    "interframe_delta",
    "probe_frame_count",
    "sample_frames",
]
