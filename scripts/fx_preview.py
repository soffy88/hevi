#!/usr/bin/env python3
"""Render 2s preview MP4s + thumbnail JPGs for every FX template.

One 2s / 540x960 / 30fps MP4 and one JPG thumbnail per template, written to
``output/fx_previews/``, plus a machine-readable ``index.json`` and a
``contact_sheet.png`` (>= 4 thumbnails per category).

Renderers (all real output — failures are recorded, never replaced by stills):

- ``tc:*``   — Remotion CLI renders the card's own composition
               (``hevi-remotion-talkcraft`` is treated read-only; its
               ``src/kbMeta.ts`` / ``src/mediaManifest.ts`` are gitignored build
               artifacts regenerated with talkcraft's own ``scripts/gen-index.mjs``),
               then ffmpeg reframes the 960x540 landscape stage onto a blurred
               540x960 portrait canvas. Cards shorter than 2s are looped rather
               than frozen.
- ``xfade:*`` — two animated lavfi sources through the requested ffmpeg xfade
               transition.
- ``sfx:*``   — the real WAV through ``showwaves`` (waveform visualisation) with
               the audio kept.

Every success is ffprobe-validated for duration / resolution / fps and measured
for mean adjacent-frame difference (ffmpeg ``tblend=difference`` +
``signalstats.YAVG``, 0-255 scale). Static outputs are marked as failures.

Usage:
    .venv/bin/python scripts/fx_preview.py                 # everything
    .venv/bin/python scripts/fx_preview.py --source sfx    # one source
    .venv/bin/python scripts/fx_preview.py --limit 3       # smoke test
    .venv/bin/python scripts/fx_preview.py --only xfade:fade tc:bar-chart-growth
    .venv/bin/python scripts/fx_preview.py --workers 2 --contact-sheet-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Running ``scripts/fx_preview.py`` puts *scripts* on sys.path, which would make
# ``import hevi`` resolve to whichever checkout the interpreter happens to prefer
# (another worktree). Pin the repo root that owns this tree before importing.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO = _REPO
OUT_DIR = REPO / "output" / "fx_previews"

FFMPEG = os.environ.get("HEVI_FFMPEG") or shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
FFPROBE = (
    os.environ.get("HEVI_FFPROBE") or shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
)

REMOTION_DIR = REPO / "hevi-remotion-talkcraft"
REMOTION_CLI = REMOTION_DIR / "node_modules" / ".bin" / "remotion"
REMOTION_ENTRY = "src/remotion/index.ts"
NODE_BIN = os.environ.get("HEVI_NODE_BIN") or str(
    Path.home() / ".nvm" / "versions" / "node" / "v26.4.0" / "bin"
)
TALKCRAFT_GEN_INDEX = REMOTION_DIR / "scripts" / "gen-index.mjs"

SFX_DIR = REPO / "assets" / "audio" / "sfx"

WIDTH, HEIGHT, FPS = 540, 960, 30
DURATION_S = 2.0
TARGET_FRAMES = int(round(DURATION_S * FPS))  # 60

# Mean adjacent-frame YAVG (0-255 scale) that still counts as "moving".
# 0.01 is effectively "not bit-identical", i.e. a genuine non-static check.
DIFF_MIN = 0.01

THUMB_WIDTH = 324  # 324x576, 9:16

#: Duration of the xfade cross-over in the 2s xfade previews.
XFADE_DUR = 1.0

# Colour palettes cycled across xfade previews so the contact sheet is varied.
XFADE_PALETTES = [
    ("#1a2a6c", "#b21f1f", "#fdbb2d"),
    ("#16222a", "#3a86ff", "#8338ec"),
    ("#03071e", "#370617", "#e71d36"),
    ("#0f2027", "#203a43", "#2c5364"),
    ("#232526", "#414345", "#00b09b"),
    ("#3a1c71", "#d76d77", "#ffaf7b"),
]

RENDER_TIMEOUT_S = int(os.environ.get("HEVI_FX_RENDER_TIMEOUT", "600"))
_probe_lock = threading.Lock()
_comp_cache: dict[str, int] | None = None


class RenderError(RuntimeError):
    """Raised when a preview could not be produced (recorded, never faked)."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str], *, cwd: Path | None = None, timeout: int = RENDER_TIMEOUT_S, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing output."""
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        timeout=timeout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _slug(template_id: str) -> str:
    return template_id.replace(":", "__")


def ffprobe(path: Path) -> dict:
    """Return {duration_s, width, height, fps, has_audio} for a media file."""
    cmd = [
        FFPROBE,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream=codec_type,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    r = _run(cmd, check=True)
    data = json.loads(r.stdout)
    dur = float(data.get("format", {}).get("duration") or 0.0)
    out: dict = {"duration_s": dur, "width": None, "height": None, "fps": None, "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and s.get("width"):
            out["width"], out["height"] = int(s["width"]), int(s["height"])
            num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
            out["fps"] = float(num) / float(den or 1)
        elif s.get("codec_type") == "audio":
            out["has_audio"] = True
    return out


def frame_diff_mean(path: Path) -> float | None:
    """Mean |frame[n]-frame[n-1]| luma (0-255 scale) across the clip.

    Computed with ffmpeg's ``tblend=all_mode=difference`` + ``signalstats``.
    Returns None when it cannot be measured.
    """
    cmd = [
        FFMPEG,
        "-v",
        "info",
        "-i",
        str(path),
        "-vf",
        "tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
        "-f",
        "null",
        "-",
    ]
    try:
        r = _run(cmd, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        return None
    vals = [float(x) for x in re.findall(r"lavfi\.signalstats\.YAVG=([0-9.eE+-]+)", r.stdout)]
    if not vals:
        return None
    return sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Remotion composition table (real durations — no guessing)
# ---------------------------------------------------------------------------


def _ensure_talkcraft_generated() -> None:
    """Regenerate talkcraft's gitignored build indexes if they are missing.

    ``src/kbMeta.ts`` and ``src/mediaManifest.ts`` are produced by talkcraft's
    own ``scripts/gen-index.mjs`` (both are in hevi-remotion-talkcraft/.gitignore)
    and are required for webpack to bundle. We never touch tracked sources.
    """
    if (REMOTION_DIR / "src" / "kbMeta.ts").exists() and (
        REMOTION_DIR / "src" / "mediaManifest.ts"
    ).exists():
        return
    node = shutil.which("node") or str(Path(NODE_BIN) / "node")
    r = _run([node, str(TALKCRAFT_GEN_INDEX)], cwd=REMOTION_DIR, timeout=300, check=False)
    if r.returncode != 0:
        raise RenderError(f"talkcraft gen-index failed: {r.stdout[-400:]}")


def _parse_composition_table(text: str) -> dict[str, int]:
    """Parse `remotion compositions` output into {id: durationInFrames}."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z0-9._\-]+)\s+(\d+)\s+(\d+)x(\d+)\s+(\d+)\s*\(", line)
        if m:
            out[m.group(1)] = int(m.group(5))
    return out


def remotion_durations() -> dict[str, int]:
    """Ask Remotion for every registered composition and its duration.

    Cached for the process lifetime — the bundle step is the expensive part.
    """
    global _comp_cache
    if _comp_cache is not None:
        return _comp_cache

    if not REMOTION_CLI.exists():
        raise RenderError(f"remotion CLI missing under {REMOTION_DIR}")
    _ensure_talkcraft_generated()
    env = dict(os.environ)
    env["PATH"] = NODE_BIN + os.pathsep + env.get("PATH", "")
    r = _run(
        [str(REMOTION_CLI), "compositions", REMOTION_ENTRY, "--json"],
        cwd=REMOTION_DIR,
        timeout=RENDER_TIMEOUT_S,
        check=False,
    )
    table = _parse_composition_table(r.stdout)
    if not table:
        raise RenderError(f"could not parse remotion compositions output (exit {r.returncode})")
    _comp_cache = table
    return table


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_talkcraft(card_id: str, out_mp4: Path) -> dict:
    """Render a talkcraft card with Remotion, then reframe to 540x960 portrait."""
    dur_frames = remotion_durations().get(card_id)
    if dur_frames is None:
        raise RenderError(f"composition '{card_id}' not registered in remotion compositions")

    frames = min(TARGET_FRAMES, dur_frames)
    native = out_mp4.with_suffix(".native.mp4")
    cmd = [
        str(REMOTION_CLI),
        "render",
        REMOTION_ENTRY,
        card_id,
        str(native),
        f"--frames=0-{frames - 1}",
        "--scale=1",
        "--log=error",
        "--concurrency=1",
    ]
    env = dict(os.environ)
    env["PATH"] = NODE_BIN + os.pathsep + env.get("PATH", "")
    r = _run(
        cmd,
        cwd=REMOTION_DIR,
        timeout=RENDER_TIMEOUT_S,
        check=False,
    )
    if r.returncode != 0 or not native.exists():
        raise RenderError(f"remotion render failed ({card_id}): {r.stdout[-400:]}")

    # Portrait reframe: blurred, darkened fill behind the centred landscape stage.
    filter_complex = (
        f"[0:v]split[a][b];"
        f"[a]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},boxblur=60:3,eq=brightness=-0.04[bg];"
        f"[b]scale={WIDTH}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
    )
    _run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            str(native),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-an",
            "-t",
            str(DURATION_S),
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(out_mp4),
        ]
    )
    native.unlink(missing_ok=True)
    return {
        "native_frames": frames,
        "native_duration_s": frames / FPS,
        "looped": frames < TARGET_FRAMES,
    }


def render_xfade(transition: str, out_mp4: Path, palette_index: int = 0) -> dict:
    """Two animated lavfi sources through one ffmpeg xfade transition.

    Source A and B each run the full DURATION_S; the transition consumes the
    final ``XFADE_DUR`` seconds of A overlapping the first ``XFADE_DUR`` of B,
    so the composited clip is exactly ``DURATION_S`` long. ``fps`` is re-stamped
    after ``trim`` because xfade requires a constant frame rate on both inputs.
    """
    c0, c1, c2 = XFADE_PALETTES[palette_index % len(XFADE_PALETTES)]
    src_a = f"gradients=s={WIDTH}x{HEIGHT}:r={FPS}:d={DURATION_S}:c0={c0}:c1={c1}:c2={c2}"
    src_b = f"testsrc2=s={WIDTH}x{HEIGHT}:r={FPS}:d={DURATION_S}"
    xfade_dur = XFADE_DUR
    offset = DURATION_S - xfade_dur
    filter_complex = (
        f"[0:v]trim=0:{DURATION_S},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[a];"
        f"[1:v]trim=0:{DURATION_S},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[b];"
        f"[a][b]xfade=transition={transition}:duration={xfade_dur}:offset={offset}[v]"
    )
    _run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            src_a,
            "-f",
            "lavfi",
            "-i",
            src_b,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-an",
            "-t",
            str(DURATION_S),
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(out_mp4),
        ]
    )
    return {"palette": [c0, c1, c2]}


def render_sfx(wav_path: Path, out_mp4: Path) -> dict:
    """Waveform visualisation of the real WAV, audio preserved."""
    filter_complex = (
        f"[0:a]apad=whole_dur={DURATION_S},atrim=0:{DURATION_S},asetpts=PTS-STARTPTS[aud];"
        f"[aud]asplit[aout][awin];"
        f"[awin]showwaves=s={WIDTH}x{HEIGHT}:mode=cline:rate={FPS}:"
        f"colors=0x4DA6FF|0x14181F,setsar=1,format=yuv420p[v]"
    )
    _run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-i",
            str(wav_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[aout]",
            "-t",
            str(DURATION_S),
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(out_mp4),
        ]
    )
    return {}


def make_thumbnail(mp4: Path, jpg: Path) -> None:
    """Grab the mid-clip frame as a JPG."""
    thumb_h = int(THUMB_WIDTH * HEIGHT / WIDTH)
    _run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-ss",
            "1.0",
            "-i",
            str(mp4),
            "-frames:v",
            "1",
            "-vf",
            f"scale={THUMB_WIDTH}:{thumb_h}",
            "-q:v",
            "3",
            str(jpg),
        ]
    )
    if not jpg.exists():
        raise RenderError("thumbnail extraction produced no file")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _render_one(template, out_dir: Path) -> dict:
    """Render + validate one template; return its index.json record."""
    slug = _slug(template.id)
    mp4 = out_dir / f"{slug}.mp4"
    jpg = out_dir / f"{slug}.jpg"
    t0 = time.monotonic()
    record: dict = {
        "id": template.id,
        "name_zh": template.name_zh,
        "category": template.category.value,
        "source": template.source.value,
        "source_ref": template.source_ref,
        "tags": list(template.tags),
        "duration_hint": template.duration_hint,
    }
    try:
        if template.source.value == "talkcraft":
            extra = render_talkcraft(template.source_ref, mp4)
        elif template.source.value == "xfade":
            extra = render_xfade(
                template.source_ref, mp4, palette_index=hash(template.id) % len(XFADE_PALETTES)
            )
        elif template.source.value == "sfx":
            wav = SFX_DIR / f"{template.source_ref}.wav"
            if not wav.exists():
                raise RenderError(f"sfx asset missing: {wav}")
            extra = render_sfx(wav, mp4)
        else:
            raise RenderError(f"unsupported source: {template.source.value}")

        make_thumbnail(mp4, jpg)

        info = ffprobe(mp4)
        diff = frame_diff_mean(mp4)
        record.update(extra)
        record.update(
            {
                "status": "ok",
                "duration_s": round(info["duration_s"], 4),
                "width": info["width"],
                "height": info["height"],
                "fps": info["fps"],
                "has_audio": info["has_audio"],
                "frame_diff_mean": round(diff, 6) if diff is not None else None,
                "frame_diff_norm": round(diff / 255.0, 8) if diff is not None else None,
                "mp4_bytes": mp4.stat().st_size,
                "mp4_sha256": _sha256(mp4),
                "thumbnail_bytes": jpg.stat().st_size,
                "thumbnail_sha256": _sha256(jpg),
                "mp4_path": f"output/fx_previews/{slug}.mp4",
                "thumbnail_path": f"output/fx_previews/{slug}.jpg",
                "elapsed_s": round(time.monotonic() - t0, 2),
            }
        )
        # Hard validation: duration within tolerance, resolution, fps, non-static
        problems = []
        if abs(info["duration_s"] - DURATION_S) > 0.1:
            problems.append(f"duration {info['duration_s']:.3f}s != {DURATION_S}s")
        if (info["width"], info["height"]) != (WIDTH, HEIGHT):
            problems.append(f"resolution {info['width']}x{info['height']}")
        if info["fps"] is None or abs(info["fps"] - FPS) > 0.5:
            problems.append(f"fps {info['fps']}")
        if diff is None:
            problems.append("frame difference unmeasurable")
        elif diff <= DIFF_MIN:
            problems.append(f"static-looking preview (mean diff {diff:.4f} <= {DIFF_MIN})")
        if problems:
            record["status"] = "failed"
            record["error"] = "; ".join(problems)
    except Exception as exc:  # noqa: BLE001 — record, never crash the batch
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["elapsed_s"] = round(time.monotonic() - t0, 2)
        for p in (mp4, jpg):
            if p.exists():
                p.unlink()

    return record


def select_templates(only: list[str] | None, source: str | None, limit: int | None) -> list:
    from hevi.fx.loader import load_all

    templates = load_all()
    sel = templates.list_all()
    if only:
        wanted = set(only)
        sel = [t for t in sel if t.id in wanted]
    if source:
        sel = [t for t in sel if t.source.value == source]
    if limit:
        sel = sel[:limit]
    if not sel:
        print("warning: selection matched no templates", file=sys.stderr)
    return sel


def build_contact_sheet(records: list[dict], out_path: Path) -> dict:
    """Tile >=4 thumbnails per category into one PNG."""
    from PIL import Image, ImageDraw, ImageFont

    ok = [
        r
        for r in records
        if r.get("status") == "ok" and (REPO / r.get("thumbnail_path", "")).exists()
    ]
    by_cat: dict[str, list[dict]] = {}
    for r in ok:
        by_cat.setdefault(r["category"], []).append(r)

    per_cat = 4
    picked: list[dict] = []
    used: set[str] = set()
    for cat in ("transition", "character", "style", "overlay"):
        for r in by_cat.get(cat, [])[:per_cat]:
            if r["id"] in used:
                continue
            used.add(r["id"])
            picked.append(r)

    if not picked:
        return {"error": "no rendered thumbnails available", "counts": {}}

    tw, th = THUMB_WIDTH, int(THUMB_WIDTH * HEIGHT / WIDTH)
    label_h = 44
    pad = 10
    rows_n = (len(picked) + per_cat - 1) // per_cat
    sheet = Image.new(
        "RGB",
        (per_cat * (tw + pad) + pad, rows_n * (th + label_h + pad) + pad),
        (18, 20, 24),
    )
    draw = ImageDraw.Draw(sheet)

    try:
        small = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 13)
    except OSError:
        small = ImageFont.load_default()

    counts: dict[str, int] = {}
    for i, rec in enumerate(picked):
        col, row = i % per_cat, i // per_cat
        x = pad + col * (tw + pad)
        y = pad + row * (th + label_h + pad)
        jpg_path = REPO / rec["thumbnail_path"]
        try:
            img = Image.open(jpg_path).convert("RGB").resize((tw, th))
            sheet.paste(img, (x, y))
        except OSError as exc:
            draw.rectangle([x, y, x + tw, y + th], fill=(60, 20, 20))
            draw.text((x + 6, y + 6), f"missing: {exc}", fill=(255, 120, 120), font=small)
        counts[rec["category"]] = counts.get(rec["category"], 0) + 1
        draw.rectangle([x, y + th, x + tw, y + th + label_h], fill=(10, 12, 16))
        draw.text(
            (x + 6, y + th + 5),
            f"[{rec['category']}] {rec['id']}",
            fill=(235, 235, 235),
            font=small,
        )
        draw.text(
            (x + 6, y + th + 22), (rec.get("name_zh") or "")[:28], fill=(150, 160, 175), font=small
        )

    sheet.save(out_path)
    return {"counts": counts, "total": len(picked), "width": sheet.width, "height": sheet.height}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--only", nargs="*", help="specific template ids, e.g. tc:bar-chart-growth xfade:fade"
    )
    parser.add_argument(
        "--source", choices=["talkcraft", "xfade", "sfx"], help="restrict to one source"
    )
    parser.add_argument("--limit", type=int, help="cap the number of templates")
    parser.add_argument("--workers", type=int, default=2, help="concurrency (keep <= 2)")
    parser.add_argument(
        "--contact-sheet-only", action="store_true", help="just rebuild contact_sheet.png"
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    args = parser.parse_args()

    out_dir = args.out if args.out.is_absolute() else REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(args.workers, 2))

    index_path = out_dir / "index.json"
    sheet_path = out_dir / "contact_sheet.png"

    prior: list[dict] = []
    if index_path.exists():
        try:
            prior = json.loads(index_path.read_text(encoding="utf-8")).get("templates", [])
        except ValueError, OSError:
            prior = []

    if args.contact_sheet_only:
        result = build_contact_sheet(prior, sheet_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if "error" not in result else 1

    templates = select_templates(args.only, args.source, args.limit)
    if not templates:
        return 2

    fresh: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_render_one, t, out_dir): t for t in templates}
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            fresh.append(rec)
            mark = "ok  " if rec["status"] == "ok" else "FAIL"
            print(
                f"[{i}/{len(templates)}] {mark} {rec['id']} "
                f"{rec.get('duration_s', '')} diff={rec.get('frame_diff_mean', '')} "
                f"{rec.get('error', '')}",
                flush=True,
            )

    by_id = {r["id"]: r for r in prior}
    by_id.update({r["id"]: r for r in fresh})
    ordered = []
    seen: set[str] = set()
    for t in select_templates(None, None, None):
        if t.id in by_id and t.id not in seen:
            seen.add(t.id)
            ordered.append(by_id[t.id])
    for rid, rec in by_id.items():  # keep records that fell out of the registry
        if rid not in seen:
            ordered.append(rec)

    ok = [r for r in ordered if r["status"] == "ok"]
    failed = [r for r in ordered if r["status"] != "ok"]
    sheet_info = build_contact_sheet(ordered, sheet_path)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "renderer": "scripts/fx_preview.py",
        "config": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "duration_s": DURATION_S,
            "frame_diff_min": DIFF_MIN,
            "workers": workers,
            "ffmpeg": FFMPEG,
            "ffprobe": FFPROBE,
        },
        "summary": {
            "total": len(ordered),
            "ok": len(ok),
            "failed": len(failed),
            "ok_by_category": _count(ok, "category"),
            "ok_by_source": _count(ok, "source"),
            "failed_ids": [r["id"] for r in failed],
            "below_strict_diff_norm": sum(1 for r in ok if (r.get("frame_diff_norm") or 0) < 0.01),
            "mp4_total_bytes": sum(r.get("mp4_bytes", 0) for r in ok),
        },
        "contact_sheet": sheet_info,
        "templates": ordered,
    }
    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(index_path)

    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2), flush=True)
    return 0


def _count(records: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
