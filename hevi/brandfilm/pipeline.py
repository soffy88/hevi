"""End-to-End delivery pipeline for Hevi BrandFilm line (line=brandfilm).

Runs the full deterministic flow:
  brief -> shot-list.md -> copy.md -> HTML/GSAP -> silent render -> beat-aligned
  algorithmic score -> mux loudness-normalized MP4 -> 3 gates -> contact sheet ->
  manifest with sha256/duration/LUFS.

Usage:
    PYTHONPATH=$PWD .venv/bin/python -m hevi.brandfilm.pipeline \
        --brief examples/brandfilm_brief.json --out artifacts/brandfilm/e2e
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .generator import generate_brandfilm_project
from .score import compose_brandfilm_score, mux_audio_video

_ROOT = Path(__file__).resolve().parents[2]
_FFPROBE = shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
_FFMPEG = shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
_L4 = _ROOT / "hevi" / "layer4_legacy" / "brandfilm" / "scripts"
_GATES = ("film_audit", "layout_audit", "frame_audit")


@dataclass(frozen=True)
class BrandfilmBrief:
    """Input contract for the brandfilm line."""

    brand_name: str
    selling_points: list[str]
    logo: str | None
    product_images: list[str]
    aspect: str  # "16:9" or "9:16"
    duration: float = 15.0
    bpm: float = 120.0
    seed: int = 42
    fps: int = 30
    output_dir: str = "output/brandfilm"

    @classmethod
    def from_json(cls, path: str | Path) -> BrandfilmBrief:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        required = ("brand_name", "selling_points")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"brief missing required keys: {missing}")
        return cls(
            brand_name=str(data["brand_name"]),
            selling_points=list(data["selling_points"]),
            logo=data.get("logo"),
            product_images=list(data.get("product_images") or []),
            aspect=str(data.get("aspect") or "16:9"),
            duration=float(data.get("duration", 15.0)),
            bpm=float(data.get("bpm", 120.0)),
            seed=int(data.get("seed", 42)),
            fps=int(data.get("fps", 30)),
            output_dir=str(data.get("output_dir") or "output/brandfilm"),
        )


def _run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    kw.setdefault("check", True)
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ffprobe_json(path: Path) -> dict[str, Any]:
    out = _run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    return json.loads(out.stdout)


def _loudness(path: Path) -> dict[str, float]:
    """Measure integrated LUFS via ffmpeg ebur128."""
    proc = _run([_FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-filter_complex", "ebur128", "-f", "null", "-"], check=False)
    text = proc.stderr
    tail = text[-2500:]
    m = re.search(r"I:\s*([-0-9.]+)\s*LUFS", tail)
    i_lufs = float(m.group(1)) if m else float("nan")
    m_peak = re.search(r"Peak:\s*([-0-9.]+)\s*dBFS", tail)
    peak = float(m_peak.group(1)) if m_peak else float("nan")
    return {"integrated_lufs": i_lufs, "true_peak_dbfs": peak}


def _contact_sheet(mp4: Path, out_png: Path, cols: int = 6, rows: int = 5) -> Path:
    _run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-i",
            str(mp4),
            "-vf",
            f"fps=2,scale=384:-1,tile={cols}x{rows}",
            "-frames:v",
            "1",
            str(out_png),
        ]
    )
    return out_png


def _cover_frame(mp4: Path, out_png: Path) -> Path:
    _run([_FFMPEG, "-y", "-v", "error", "-i", str(mp4), "-vf", "scale=960:-1", "-frames:v", "1", str(out_png)])
    return out_png


def _run_gates(project: Path, film_html: Path, silent_mp4: Path) -> dict[str, Any]:
    """Run all three upstream gates; they stamp <project>/.gates/<name>.ok.

    score_lib.write() refuses to emit audio unless those stamps exist, so the
    gates must pass before composition. Returns per-gate structured results.
    """
    results: dict[str, Any] = {}

    proc = _run([sys.executable, str(_L4 / "film_audit.py"), str(film_html)], check=False)
    results["film_audit"] = {
        "returncode": proc.returncode,
        "failed": len(re.findall(r"^\s+([1-9]\d*) failed", proc.stdout, flags=re.M)),
        "report": proc.stdout,
    }

    lproc = _run(["node", str(_L4 / "layout_audit.mjs"), str(film_html)], check=False)
    results["layout_audit"] = {
        "returncode": lproc.returncode,
        "failed": len(re.findall(r"FAIL", lproc.stdout)),
        "report": lproc.stdout,
    }

    pproc = _run([sys.executable, str(_L4 / "frame_audit.py"), str(silent_mp4)], check=False)
    results["frame_audit"] = {
        "returncode": pproc.returncode,
        "failed": len(re.findall(r"FAIL", pproc.stdout)),
        "report": pproc.stdout,
    }

    results["all_passed"] = all(
        isinstance(v, dict) and v.get("returncode") == 0
        for k, v in results.items()
        if k in _GATES
    )
    return results


def run_brandfilm_pipeline(brief: BrandfilmBrief, engine: str = "hyperframes") -> dict[str, Any]:
    """Execute full pipeline and return delivery manifest dict."""
    out_root = Path(brief.output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    project_dir = out_root / "project"
    project = generate_brandfilm_project(project_dir, aspect=brief.aspect, brand_name=brief.brand_name)

    film_dir = project / "film"
    film_html = film_dir / "index.html"

    renders_dir = film_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    silent_mp4 = renders_dir / "silent.mp4"

    # 1. Render silent video frame-by-frame
    hf = shutil.which("hyperframes") or "hyperframes"
    if engine == "hyperframes":
        _run([hf, "render", str(film_dir), "-q", "looks", "--fps", str(brief.fps), "-o", str(silent_mp4)])
    else:
        _render_with_playwright(film_dir, silent_mp4, brief.fps, brief.aspect)

    # 4. Three quality gates (must pass before scoring — score_lib requires stamps)
    gates = _run_gates(project, film_html, silent_mp4)

    # 5. Compose beat-aligned score (requires .gates/*.ok to write the wav)
    score_wav = film_dir / "renders" / "score.wav"
    score_meta = compose_brandfilm_score(
        score_wav, duration=brief.duration, bpm=brief.bpm, seed=brief.seed
    )

    # 6. Mux audio+video and loudness normalize to -14 LUFS
    final_mp4 = out_root / f"brandfilm_{brief.brand_name.replace(' ', '_')}_{brief.aspect.replace(':', 'x')}.mp4"
    mux_audio_video(silent_mp4, score_wav, final_mp4, target_lufs=-14.0)

    # 7. Contact sheet + cover
    cover_png = out_root / "cover.jpg"
    _cover_frame(final_mp4, cover_png)
    contact_png = out_root / "contact_sheet.jpg"
    _contact_sheet(final_mp4, contact_png)

    # 7. Evidence manifest
    fb = _ffprobe_json(final_mp4)
    vs = next((s for s in fb.get("streams", []) if s.get("codec_type") == "video"), {})
    aud = next((s for s in fb.get("streams", []) if s.get("codec_type") == "audio"), {})
    loud = _loudness(final_mp4)

    manifest = {
        "brand_name": brief.brand_name,
        "aspect": brief.aspect,
        "duration_s_target": brief.duration,
        "outputs": {
            "final_mp4": str(final_mp4),
            "cover": str(cover_png),
            "contact_sheet": str(contact_png),
            "shot_list": str(project / "shot-list.md"),
            "copy": str(project / "copy.md"),
            "assets_manifest": str(project / "assets.md"),
            "silent_mp4": str(silent_mp4),
            "score_wav": str(score_wav),
            "beat_alignment": score_meta,
        },
        "ffprobe": {
            "width": int(vs.get("width", 0)),
            "height": int(vs.get("height", 0)),
            "fps": vs.get("r_frame_rate", ""),
            "codec_video": vs.get("codec_name", ""),
            "codec_audio": aud.get("codec_name", ""),
            "duration_s": float(fb.get("format", {}).get("duration", 0.0)),
            "has_audio_track": bool(aud),
        },
        "audio_loudness": loud,
        "sha256": _sha256(final_mp4),
        "quality_gates": gates,
        "engine": engine,
    }
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _render_with_playwright(film_dir: Path, out_mp4: Path, fps: int, aspect: str) -> None:
    """Deterministic CPU fallback: seek paused GSAP timeline and screenshot."""
    import base64
    import tempfile
    from pathlib import Path as _P

    from playwright.sync_api import sync_playwright

    W, H = (1920, 1080) if aspect == "16:9" else (1080, 1920)
    dur, step = 15.0, 1.0 / fps
    tmpdir = _P(tempfile.mkdtemp(prefix="brandfilm_frames_"))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage", "--allow-file-access-from-files"]
            )
            page = browser.new_page(viewport={"width": W, "height": H})
            page.goto((film_dir / "index.html").as_uri())
            page.wait_for_function("() => window.__timelines && Object.keys(window.__timelines).length > 0")
            for i in range(int(round(dur / step)) + 1):
                t = min(i * step, dur)
                page.evaluate(
                    "(t) => { for (const tl of Object.values(window.__timelines)) tl.seek(t, false); }", t
                )
                shot = page.screenshot(clip={"x": 0, "y": 0, "width": W, "height": H})
                (tmpdir / f"f{i:05d}.png").write_bytes(shot)
            browser.close()

        _run(
            [
                _FFMPEG,
                "-y",
                "-v",
                "error",
                "-framerate",
                str(fps),
                "-i",
                str(tmpdir / "f%05d.png"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
                "-preset",
                "veryfast",
                "-movflags",
                "+faststart",
                str(out_mp4),
            ]
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Hevi BrandFilm E2E pipeline")
    ap.add_argument("--brief", required=True, help="path to JSON brief")
    ap.add_argument("--output-dir", default=None, help="override output dir")
    ap.add_argument("--engine", choices=["hyperframes", "playwright"], default="hyperframes")
    args = ap.parse_args(argv)

    brief = BrandfilmBrief.from_json(args.brief)
    if args.output_dir:
        brief.output_dir = args.output_dir

    manifest = run_brandfilm_pipeline(brief, engine=args.engine)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["quality_gates"]["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
