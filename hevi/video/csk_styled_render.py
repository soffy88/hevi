"""Creator Style Kit (threeaus/creator-style-kit, MIT) support for hevi's HyperFrames line.

Integration design
------------------
* The kit itself lives OUTSIDE the hevi repo
  (``~/projects/_refs/creator-style-kit``, overridable via ``HEVI_CSK_HOME``).
  Only the generated style catalogue snapshot is kept inside hevi; the kit's
  own scripts (scaffold.py / build_style.py / compose.py) do the scene
  building.  This keeps ~180 MB of fonts, SFX WAVs and runtime assets out of
  the repo (hevi's working tree is deliberately kept small).
* Renders are deterministic and seek-based: the kit's timelines are seek-safe
  (GSAP ``tl.set``/``tl.to``, seeded PRNG), so we load the scaffolded project
  in headless Chromium (Playwright), mount each hosted composition the way
  the HyperFrames runtime does (template -> host div -> eval its script) and
  seek its registered GSAP timeline per frame.  hevi's existing ``hyperframes_service`` is deliberately NOT
  reused for capture: it opens a fresh browser per frame with a 100 ms
  virtual-time budget, which would freeze every CSK composition on its first
  instant.  The ffmpeg encoding flags are reused verbatim
  (libx264 / yuv420p / scale / medium / crf 18).
* Fonts: bundled fonts ship in the kit (all OFL-1.1, subset per project at
  build).  MiSans / 优设标题黑 are NOT redistributable: the kit fetches them
  itself via ``scripts/fetch_fonts.py`` (sha256-checked).  Styles needing them
  raise :class:`CskError` until the fetch has run.
* Sound: each style's cue kit (Kenney/uisfx, CC0) is baked into the project
  by the kit's build_style.py; post-render mix/QA stays the kit's
  ``sound_pass.py``.  This is a separate resource from hevi's
  ``audio.sfx_render`` (earshot, code-rendered) and is intentionally not
  merged — see the capability description.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import yaml
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class CskError(RuntimeError):
    """Something is wrong with the creator-style-kit setup or a render step."""


CSK_ENV = "HEVI_CSK_HOME"
CSK_DEFAULT_HOME = Path.home() / "projects" / "_refs" / "creator-style-kit"

# Source: threeaus/creator-style-kit, MIT.  Kept here so the catalogue can be
# regenerated deterministically; the single source of truth stays in the kit.
CSK_SOURCE_URL = "https://github.com/threeaus/creator-style-kit"

REQUIRED_KIT_PATHS = ("styles", "scripts/scaffold.py", "runtime/kit.js")


def resolve_kit_home() -> Path:
    """Return the kit checkout, raising :class:`CskError` when unusable."""
    home = Path(os.environ.get(CSK_ENV, CSK_DEFAULT_HOME)).expanduser()
    missing = [p for p in REQUIRED_KIT_PATHS if not (home / p).exists()]
    if missing:
        raise CskError(
            f"creator-style-kit not usable at {home} "
            f"(missing: {', '.join(missing)}); set {CSK_ENV} or clone "
            f"{CSK_SOURCE_URL}"
        )
    return home


def load_style_specs(kit_home: Path | None = None) -> list[dict[str, Any]]:
    """Parse every ``styles/*/style.yaml`` into a sorted catalogue list."""
    home = kit_home or resolve_kit_home()
    specs = []
    for style_yaml in sorted((home / "styles").glob("*/style.yaml")):
        spec = yaml.safe_load(style_yaml.read_text(encoding="utf-8"))
        specs.append(
            {
                "id": spec.get("id"),
                "order": spec.get("order", 99),
                "name_zh": spec.get("name", {}).get("zh", ""),
                "name_en": spec.get("name", {}).get("en", ""),
                "essence": spec.get("essence", ""),
                "best_for": spec.get("best_for", []),
                "not": spec.get("not", []),
                "motion": spec.get("motion", {}),
                "colors": spec.get("colors", {}),
                "layout": spec.get("layout", {}),
                "fonts": {
                    role: {
                        "family": f.get("family"),
                        "weight": f.get("weight"),
                        "license": f.get("license"),
                        "source": f.get("source"),
                        "bundled": f.get("bundled", False),
                    }
                    for role, f in (spec.get("fonts") or {}).items()
                },
                "sound": {
                    "character": spec.get("sound", {}).get("character", ""),
                    "rules": spec.get("sound", {}).get("rules", {}),
                    "roles": list(spec.get("sound", {}).get("kit", {}).keys()),
                },
            }
        )
    specs.sort(key=lambda s: (s["order"], s["id"]))
    return specs


def style_ids(kit_home: Path | None = None) -> list[str]:
    return [s["id"] for s in load_style_specs(kit_home)]


def kit_commit(kit_home: Path | None = None) -> str:
    """Best-effort git commit of the kit checkout ("" when unknown)."""
    home = kit_home or resolve_kit_home()
    try:
        out = subprocess.run(
            ["git", "-C", str(home), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - best effort only
        return ""


def scaffold_project(
    kit_home: Path,
    style_id: str,
    content: dict[str, Any],
    project_dir: Path,
) -> float:
    """Run the kit's scaffold.py; return the planned total duration (seconds)."""
    if style_id not in style_ids(kit_home):
        raise CskError(f"unknown style '{style_id}'")
    if not isinstance(content, dict) or "name" not in content or "beats" not in content:
        raise CskError("content must be a beats JSON object with 'name' and 'beats'")
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    beats_path = project_dir / "beats.json"
    beats_path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    env = dict(os.environ)
    # build_style.py shells out to the bare `pyftsubset` console script, which
    # lives next to the interpreter when fonttools is installed in a venv.
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.run(
        [
            sys.executable,
            str(kit_home / "scripts" / "scaffold.py"),
            style_id,
            str(project_dir),
            "--content",
            str(beats_path),
            "--init",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    if proc.returncode != 0:
        raise CskError(
            f"scaffold.py failed for style '{style_id}': "
            f"{(proc.stderr or proc.stdout)[-2000:]}"
        )
    # scaffold prints: "wrote <path> (<n> beats, <total:.2f>s, style <id>)"
    match = re.search(r"\((\d+)\s+beats?,\s*([\d.]+)s,\s*style\s+\S+\)", proc.stdout)
    if not match:
        raise CskError(
            f"scaffold.py did not report a duration: {proc.stdout[-1000:]}"
        )
    return float(match.group(2))


def _serve_dir(project_dir: Path) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    """Serve a HyperFrames project dir over loopback HTTP (file:// XHR fails)."""
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(SimpleHTTPRequestHandler, directory=str(project_dir)),
    )
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, thread, f"http://127.0.0.1:{port}/index.html"


_MOUNT_SHIM = """
async () => {
  // HyperFrames runtime shim: fetch each hosted composition, mount its
  // <template> content into the host div (so its relative csk/ asset paths
  // resolve at the project root) and execute its inline script, which
  // registers window.__timelines["<comp-id>"].
  window.__timelines = window.__timelines || {};
  const hosts = [...document.querySelectorAll('[data-composition-src]')];
  const mounted = [];
  for (const host of hosts) {
    const src = host.getAttribute('data-composition-src');
    const html = await (await fetch(src)).text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const tpl = doc.querySelector('template');
    if (!tpl) continue;
    // A <script> cloned from a template executes on insertion; remove it from
    // the fragment and eval it exactly once, or the composition builds two
    // overlay sets and only the second timeline gets registered/seeked.
    const script = tpl.content.querySelector('script');
    const code = script ? script.textContent : null;
    if (script) script.remove();
    host.appendChild(document.importNode(tpl.content, true));
    if (code) window.eval(code);
    mounted.push(host.getAttribute('data-composition-id'));
  }
  return mounted;
}
"""


async def _render_project_frames(
    project_dir: Path,
    frames_dir: Path,
    *,
    fps: int,
    duration_s: float,
    width: int = 1080,
    height: int = 1920,
) -> int:
    """Seek-based deterministic capture of a HyperFrames project."""
    from playwright.async_api import async_playwright

    frames_dir.mkdir(parents=True, exist_ok=True)
    server, _thread, url = _serve_dir(project_dir)
    total_frames = max(1, int(round(duration_s * fps)))
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-gpu"]
            )
            try:
                page = await browser.new_page(
                    viewport={"width": width, "height": height}
                )
                # The host page's own inline script writes __timelines["main"]
                # before any runtime exists; predefine it so that is not an error.
                await page.add_init_script(
                    "window.__timelines = window.__timelines || {};"
                )
                await page.goto(url)
                await page.wait_for_function(
                    "window.gsap && window.CSK", timeout=30000
                )
                mounted = await page.evaluate(_MOUNT_SHIM)
                if not mounted:
                    raise CskError("no composition could be mounted from index.html")
                await page.wait_for_function(
                    "document.fonts.status === 'loaded'", timeout=30000
                )
                seek_all = (
                    "Object.entries(window.__timelines || {})"
                    ".filter(([k]) => k !== 'main')"
                    ".forEach(([, tl]) => tl.pause(T))"
                )
                await page.evaluate(seek_all.replace("T", "0"))
                await page.wait_for_timeout(60)
                for idx in range(total_frames):
                    t = idx / fps
                    await page.evaluate(seek_all.replace("T", f"{t:.4f}"))
                    await page.wait_for_timeout(40)
                    await page.screenshot(
                        path=str(frames_dir / f"frame_{idx:04d}.png")
                    )
            finally:
                await browser.close()
    finally:
        server.shutdown()
    return total_frames


def _encode_mp4(frames_dir: Path, output: Path, *, fps: int, width: int, height: int) -> None:
    """Encode a frame sequence with the same flags as hyperframes_service."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise CskError("ffmpeg not found on PATH (needed for mp4 encoding)")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        f"scale={width}:{height}",
        "-preset",
        "medium",
        "-crf",
        "18",
        str(output),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not output.exists():
        raise CskError(f"ffmpeg encode failed: {(proc.stderr or '')[-1000:]}")


def render_project_mp4(
    project_dir: Path,
    output: Path,
    *,
    fps: int = 24,
    duration_s: float,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Scaffolded HyperFrames project -> deterministic MP4 (sync wrapper)."""
    project_dir = Path(project_dir)
    if not (project_dir / "index.html").exists():
        raise CskError(f"not a scaffolded project (index.html missing): {project_dir}")
    frames_dir = project_dir.parent / (project_dir.name + "_frames")
    if frames_dir.exists():
        shutil.rmtree(frames_dir)

    async def _go() -> int:
        return await _render_project_frames(
            project_dir, frames_dir, fps=fps, duration_s=duration_s,
            width=width, height=height,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_go())
    else:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, _go()).result()
    _encode_mp4(frames_dir, output, fps=fps, width=width, height=height)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return Path(output)
