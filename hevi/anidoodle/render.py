"""Render anidoodle stills, drawing-process clips and patched ranges.

Every function writes into ``HEVI_ANIDOODLE_OUT`` (default ``data/anidoodle``)
and returns a JSON-ready dict with the artefact path, its sha256 and the
measurements a reviewer needs.  Aspect ratio and duration come from the style's
own film: the engine composes for its native frame, so this module never
pretends a 1:1 plate is a 9:16 delivery.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .catalog import get_style
from .engine import (
    AnidoodleError,
    engine_dir,
    engine_version,
    film_meta,
    output_root,
    run_node,
    sha256_file,
)

_STILL_RE = re.compile(
    r"frame\s+(?P<frame>\d+).*?md5\s+(?P<md5>[0-9a-f]{32}).*?reproducible\s+->\s+(?P<path>.+?)\s+\("
)


def _job_dir(prefix: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = output_root() / f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _cache_dir() -> Path:
    path = output_root() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _film_source_hash(film: str) -> str:
    source = engine_dir() / "src" / "canvas-core" / f"{film}.ts"
    if not source.is_file():
        raise AnidoodleError(f"film source missing: {source}")
    return sha256_file(source)


def _still_cache_key(film: str, frame: int, scale: float) -> dict[str, Any]:
    return {
        "film": film,
        "frame": int(frame),
        "scale": scale,
        "engine_version": engine_version(),
        "source_sha256": _film_source_hash(film),
    }


def _tail(text: str, limit: int = 1600) -> str:
    return (text or "")[-limit:]


def render_still(
    style_id: str,
    *,
    frame: int | None = None,
    scale: float = 1.0,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Render the style's finished plate, or one requested frame of its film."""

    style = get_style(style_id)
    film = style.draw_film
    meta = film_meta(film)
    total = int(meta["durationFrames"])
    target = total - 1 if frame is None else int(frame)
    if target < 0 or target >= total:
        raise AnidoodleError(f"frame {target} outside film {film} (0..{total - 1})")
    key = _still_cache_key(film, target, float(scale))
    cache_file = _cache_dir() / "stills" / f"{film}-{target}-{scale}.json"
    if use_cache and cache_file.is_file():
        try:
            row = json.loads(cache_file.read_text(encoding="utf-8"))
            cached = Path(row["path"])
            if cached.is_file() and row.get("key") == key:
                return {
                    **row["result"],
                    "cached": True,
                    "path": str(cached),
                }
        except Exception:
            pass

    job = _job_dir(f"still-{style.id}")
    out = job / f"{film}-{target}.png"
    started = time.monotonic()
    result = run_node(
        [
            "tools/still.mjs",
            film,
            "--frame",
            str(target),
            "--scale",
            str(scale),
            "--out",
            str(out),
        ],
        timeout=600,
    )
    if result.returncode != 0 or not out.is_file():
        raise AnidoodleError(
            f"still failed ({result.returncode}): {_tail(result.stderr or result.stdout)}"
        )
    text = result.stdout or ""
    match = next((m for m in _STILL_RE.finditer(text) if m.group("path").strip() == str(out)), None)
    if not match:
        match = next(iter(_STILL_RE.finditer(text)), None)
    payload = {
        "style": style.to_dict(),
        "film": film,
        "frame": target,
        "frames_total": total,
        "width": int(meta.get("W", 0)),
        "height": int(meta.get("H", 0)),
        "fps": int(meta.get("fps", 0)),
        "scale": float(scale),
        "md5": match.group("md5") if match else "",
        "reproducible": "reproducible" in text,
        "sha256": sha256_file(out),
        "path": str(out),
        "elapsed_s": round(time.monotonic() - started, 2),
        "elapsed_log": _tail(text, 800),
    }
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"key": key, "path": str(out), "result": payload}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {**payload, "cached": False}


def render_gallery(*, scale: float = 0.5) -> dict[str, Any]:
    """Render the nine-plate contact sheet that explains the medium at a glance."""

    film = "styleGallery"
    meta = film_meta(film)
    job = _job_dir("gallery")
    out = job / "style-gallery.png"
    result = run_node(
        [
            "tools/still.mjs",
            film,
            "--frame",
            "0",
            "--scale",
            str(scale),
            "--out",
            str(out),
        ],
        timeout=600,
    )
    if result.returncode != 0 or not out.is_file():
        raise AnidoodleError(
            f"gallery failed ({result.returncode}): {_tail(result.stderr or result.stdout)}"
        )
    return {
        "film": film,
        "width": int(meta.get("W", 0)),
        "height": int(meta.get("H", 0)),
        "scale": float(scale),
        "sha256": sha256_file(out),
        "path": str(out),
        "elapsed_log": _tail(result.stdout or "", 600),
    }


def render_draw_clip(
    style_id: str,
    *,
    poster_frame: int | None = None,
    scale: float = 1.0,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Render the style's drawing-process film (last frame = the finished plate)."""

    style = get_style(style_id)
    film = style.draw_film
    meta = film_meta(film)
    total = int(meta["durationFrames"])
    poster = total - 2 if poster_frame is None else int(poster_frame)
    if not 0 <= poster < total:
        raise AnidoodleError(f"poster frame {poster} outside 0..{total - 1}")
    job = _job_dir(f"draw-{style.id}")
    out = job / f"{film}.mp4"
    hashes = job / "frame-hashes.txt"
    started = time.monotonic()
    args = [
        "tools/render.mjs",
        film,
        "--scale",
        str(scale),
        "--poster-frame",
        str(poster),
        "--hashes",
        str(hashes),
        "--out",
        str(out),
        *(extra_args or []),
    ]
    result = run_node(args, timeout=1800)
    if result.returncode != 0 or not out.is_file():
        raise AnidoodleError(
            f"draw clip failed ({result.returncode}): {_tail(result.stderr or result.stdout)}"
        )
    text = result.stdout or ""
    deterministic = "hash-identical" in text and "determinism:" in text
    m = re.search(r"determinism:\s*(\d+/\d+)", text)
    return {
        "style": style.to_dict(),
        "film": film,
        "width": int(meta.get("W", 0)),
        "height": int(meta.get("H", 0)),
        "fps": int(meta.get("fps", 0)),
        "duration_frames": total,
        "duration_s": round(total / float(meta.get("fps", 30)), 3),
        "poster_frame": poster,
        "elapsed_s": round(time.monotonic() - started, 2),
        "determinism": m.group(1) if m else "",
        "deterministic": deterministic,
        "sha256": sha256_file(out),
        "path": str(out),
        "hashes": str(hashes) if hashes.is_file() else "",
        "elapsed_log": _tail(text, 1200),
    }


def render_partial(
    style_id: str,
    *,
    start_s: float,
    end_s: float,
    base_mp4: str | Path,
    poster_frame: int | None = None,
) -> dict[str, Any]:
    """Re-render only ``[start_s, end_s)`` and splice it into a copy of the film.

    Anidoodle's range render is silent by design; this path is for picture-only
    clips.  A scored film must be re-rendered whole so its music stays aligned.
    """

    base = Path(base_mp4).expanduser().resolve()
    if not base.is_file():
        raise AnidoodleError(f"base film not found: {base}")
    if not 0 <= start_s < end_s:
        raise AnidoodleError("start_s must be >= 0 and < end_s")
    style = get_style(style_id)
    film = style.draw_film
    meta = film_meta(film)
    fps = int(meta.get("fps", 30))
    total = int(meta["durationFrames"])
    start_f = round(start_s * fps)
    end_f = min(total, round(end_s * fps))
    if end_f <= start_f:
        raise AnidoodleError("range is shorter than one frame")
    job = _job_dir(f"patch-{style.id}")
    patch = job / f"patch-{start_f}-{end_f}.mp4"
    started = time.monotonic()
    result = run_node(
        [
            "tools/render.mjs",
            film,
            "--from",
            str(start_f),
            "--to",
            str(end_f),
            "--out",
            str(patch),
        ],
        timeout=1200,
    )
    if result.returncode != 0 or not patch.is_file():
        raise AnidoodleError(
            f"range render failed ({result.returncode}): {_tail(result.stderr or result.stdout)}"
        )

    out = job / f"{base.stem}-patched.mp4"
    pieces: list[Path] = []
    head = job / "head.mp4"
    tail = job / "tail.mp4"
    if start_s > 0 and _ffmpeg(
        ["-ss", "0", "-to", f"{start_s:.3f}", "-i", str(base), "-c", "copy", str(head)]
    ):
        pieces.append(head)
    pieces.append(patch)
    if end_s * fps < total and _ffmpeg(
        ["-ss", f"{end_s:.3f}", "-i", str(base), "-c", "copy", str(tail)]
    ):
        pieces.append(tail)
    listfile = job / "concat.txt"
    listfile.write_text(
        "".join(f"file '{piece.as_posix()}'\n" for piece in pieces), encoding="utf-8"
    )
    if not _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(out)]):
        raise AnidoodleError("ffmpeg could not splice the patched range")
    return {
        "style": style.to_dict(),
        "film": film,
        "range_s": [start_s, end_s],
        "range_frames": [start_f, end_f],
        "elapsed_s": round(time.monotonic() - started, 2),
        "rerendered_seconds": round((end_f - start_f) / fps, 3),
        "total_seconds": round(total / fps, 3),
        "sha256": sha256_file(out),
        "path": str(out),
        "base": str(base),
        "note": "range renders are silent; re-render the whole film when it has a score",
    }


def _ffmpeg(args: list[str]) -> bool:
    import subprocess

    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=1200,
    )
    return result.returncode == 0
