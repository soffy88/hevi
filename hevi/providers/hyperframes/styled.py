"""Styled explainer films on the vendored lanshu kits (clean-room integration).

The upstream ``cclank/lanshu`` explainer toolkit (MIT) ships nine HyperFrames
styles.  This module wires them into Hevi as the ``hyperframes_styled`` video
provider: it builds a film project for one style, syncs a locally voiced story
(piper narration + faster-whisper word times), vendors the CDN libraries so the
render is offline-capable, and renders through the HyperFrames CLI.

Design notes
------------
* Every style is sourced only from ``kits/<style>/starter`` — never from
  ``examples/`` (the ``examples/kv-cache`` directory holds the upstream
  reference films and must stay off the render path).  ``beats.js`` is then
  generated from the input ``story.json`` so the picture is driven by the
  narration, not by the vendored demo.
* Nothing here copies OpenMontage code; the only upstream is lanshu (MIT) plus
  the CMU motion data used elsewhere.
* Rendering is delegated to the ``hyperframes`` binary.  If it is missing the
  call raises instead of silently faking an output.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STYLES: tuple[str, ...] = (
    "v1-editorial",
    "v2-signal",
    "v3-notebook",
    "v4-paper",
    "v5-comic",
    "v6-cinematic",
    "v7-drafting",
    "v8-chalkboard",
    "v9-clay",
)

#: the two jsDelivr libraries the upstream reference film pulls…
_GSAP_URL = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
_THREE_MODULE_URL = "https://cdn.jsdelivr.net/npm/three@0.181.2/build/three.module.js"
_THREE_ADDONS_URL = "https://cdn.jsdelivr.net/npm/three@0.181.2/examples/jsm/"
#: …and the repo-relative forms the vendored kit starters use.
_GSAP_REL = "../../../../hevi/providers/hyperframes/lanshu_assets/node_modules/gsap/dist/gsap.min.js"
_THREE_MODULE_REL = "../../../../hevi/providers/hyperframes/lanshu_assets/node_modules/three/build/three.module.js"
_THREE_ADDONS_REL = "../../../../hevi/providers/hyperframes/lanshu_assets/node_modules/three/examples/jsm/"


class StyledRenderError(RuntimeError):
    """A styled explainer could not be built or rendered."""


def repo_root() -> Path:
    """The hevi-omrender worktree root (four levels above this file)."""
    return Path(__file__).resolve().parents[3]


def lanshu_root() -> Path:
    return repo_root() / "third_party" / "lanshu_explainer"


def vendor_root() -> Path:
    return Path(__file__).resolve().parent / "lanshu_assets" / "node_modules"


def _render_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env["PATH"] = f"/home/soffy/.local/bin:/home/soffy/.nvm/versions/node/v26.4.0/bin:{env.get('PATH', '')}"
    env.setdefault("PYTHON", sys.executable)
    # HyperFrames aborts a render when an ancestor process it captured disappears
    # (render_cancelled_parent_exited).  Our renders are driven by an agent/CI
    # parent whose process tree is not stable, so opt into detached rendering.
    env["HYPERFRAMES_RENDER_DETACHED"] = "1"
    return env


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env or _render_env(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-800:]
        raise StyledRenderError(f"{' '.join(cmd[:3])} … failed ({proc.returncode}):\n{tail}")


def style_source(style: str) -> Path:
    """The directory the film project is copied from (starter only, never examples)."""
    if style not in STYLES:
        raise StyledRenderError(f"unknown style {style!r}; one of {STYLES}")
    starter = lanshu_root() / "kits" / style / "starter"
    if (starter / "index.html").is_file():
        return starter
    raise StyledRenderError(f"no starter for style {style!r}")


def _ensure_tools(project: Path, style: str) -> None:
    """The reference films ship only tools/sfx.py; take the shell driver (and its
    style-specific helpers) from the starter so the sound bed can be rebuilt."""
    starter_tools = lanshu_root() / "kits" / style / "starter" / "tools"
    if not starter_tools.is_dir():
        return
    project_tools = project / "tools"
    project_tools.mkdir(parents=True, exist_ok=True)
    for item in starter_tools.iterdir():
        dest = project_tools / item.name
        if not dest.exists():
            shutil.copy2(item, dest)


def _vendor_cdn(project: Path) -> None:
    """Point every library tag at a project-local vendored copy.

    The starters reference the vendored libs by a ``../../../../hevi/...``
    path (relative to the kit inside this repo).  A HyperFrames project may
    only load assets inside its own root, so GSAP and Three.js are copied into
    ``assets/vendor/`` and the tag rewritten.  The jsDelivr forms the upstream
    reference films use are rewritten by the same pass.
    """
    html_path = project / "index.html"
    html = html_path.read_text(encoding="utf-8")
    changed = False
    vendor = project / "assets" / "vendor"

    if _GSAP_URL in html or _GSAP_REL in html:
        src = vendor_root() / "gsap" / "dist" / "gsap.min.js"
        if not src.is_file():
            raise StyledRenderError(f"vendored gsap missing: {src}")
        vendor.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, vendor / "gsap.min.js")
        html = html.replace(_GSAP_URL, "assets/vendor/gsap.min.js")
        html = html.replace(_GSAP_REL, "assets/vendor/gsap.min.js")
        changed = True

    if _THREE_MODULE_URL in html or _THREE_MODULE_REL in html:
        three_src = vendor_root() / "three"
        if not (three_src / "build" / "three.module.js").is_file():
            raise StyledRenderError(f"vendored three missing: {three_src}")
        vendor.mkdir(parents=True, exist_ok=True)
        shutil.copy2(three_src / "build" / "three.module.js", vendor / "three.module.js")
        shutil.copy2(three_src / "build" / "three.core.js", vendor / "three.core.js")
        addons = vendor / "three-addons"
        if not addons.is_dir():
            shutil.copytree(three_src / "examples" / "jsm", addons)
        html = html.replace(_THREE_MODULE_URL, "./assets/vendor/three.module.js")
        html = html.replace(_THREE_ADDONS_URL, "./assets/vendor/three-addons/")
        html = html.replace(_THREE_MODULE_REL, "./assets/vendor/three.module.js")
        html = html.replace(_THREE_ADDONS_REL, "./assets/vendor/three-addons/")
        changed = True

    if changed:
        html_path.write_text(html, encoding="utf-8")


def _patch_puppeteer_sandbox(project: Path) -> None:
    """Add ``--no-sandbox`` to any kit helper that launches the bundled Chrome.

    Some kits read their sound cues back by driving puppeteer; on this host the
    headless shell cannot start its own sandbox, so the launch args are patched
    in the copied project (the vendored kit is left untouched).
    """
    kit_dir = project / "lib" / "kit"
    if not kit_dir.is_dir():
        return
    for mjs in kit_dir.glob("*.mjs"):
        text = mjs.read_text(encoding="utf-8")
        if "--no-sandbox" in text or ".launch(" not in text:
            continue
        patched = re.sub(r"args:\s*\[", 'args: ["--no-sandbox", ', text, count=1)
        if patched != text:
            mjs.write_text(patched, encoding="utf-8")


def _patch_sfxlib(project: Path) -> None:
    """Make the procedural sound-bed generators safe for non-positive lengths.

    The reference films hard-code a few cue times from the story they were built
    with; with a re-voiced story a computed span can go negative.  Clamp the
    sample counts instead of letting numpy raise (the vendored kit is untouched).
    """
    lib = project / "lib" / "sfxlib.py"
    if not lib.is_file():
        return
    text = lib.read_text(encoding="utf-8")
    patched = text.replace("n = int(dur * SR)", "n = max(1, int(dur * SR))")
    patched = patched.replace("i = int(start * SR)", "i = max(0, int(start * SR))")
    patched = patched.replace("i = int(t * SR)", "i = max(0, int(t * SR))")
    if patched != text:
        lib.write_text(patched, encoding="utf-8")


def _patch_sfx_performed(project: Path) -> None:
    sfx_py = project / "tools" / "sfx.py"
    if not sfx_py.is_file():
        return
    text = sfx_py.read_text(encoding="utf-8")
    patched = text.replace("PERFORMED: set[int] = set()", "PERFORMED: set[int] = set(range(1, 100))")
    if patched != text:
        sfx_py.write_text(patched, encoding="utf-8")


def _stamp_durations(project: Path, story: dict[str, Any]) -> None:
    """Point the film's clip/audio durations at the synced story.

    ``tools/stamp.py`` only rewrites ``data-stamp`` markers (used by the
    starters).  The reference films carry literal durations from the story they
    were built with, so the story-length value is rewritten wholesale and the
    narration audio element gets the real wav length.
    """
    html_path = project / "index.html"
    html = html_path.read_text(encoding="utf-8")

    if "data-stamp=" in html:
        _run([sys.executable, str(lanshu_root() / "tools" / "stamp.py"), str(project)])
        html = html_path.read_text(encoding="utf-8")

    story_dur = max(
        float(story.get("duration") or 0.0),
        float((story.get("recap") or {}).get("end") or 0.0),
    )
    narration = project / "assets" / "audio" / "narration.wav"
    narr_dur = story_dur
    if narration.is_file():
        narr_dur = float(
            subprocess.check_output(
                [
                    "/home/soffy/.local/bin/ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(narration),
                ]
            ).decode()
        )

    # narration audio element (id="narration") carries the spoken length
    html = re.sub(
        r'(<audio[^>]*id="narration"[^>]*data-duration=")[^"]*(")',
        rf"\g<1>{narr_dur:g}\g<2>",
        html,
    )
    # every remaining clip duration that equalled the old story length becomes the new one
    durations = [float(x) for x in re.findall(r'data-duration="([\d.]+)"', html)]
    if durations:
        old = max(durations)
        for literal in {f"{old:g}", str(old)}:
            html = html.replace(f'data-duration="{literal}"', f'data-duration="{story_dur:g}"')

    html_path.write_text(html, encoding="utf-8")


def _build_sfx(project: Path, style: str) -> None:
    env = _render_env()
    sfx_sh = (project / "tools" / "sfx.sh").resolve()
    if sfx_sh.is_file():
        _run(["bash", str(sfx_sh)], cwd=project, env=env)
    else:  # every starter ships one; a missing driver is a build error, not a skip
        raise StyledRenderError(f"no sound-bed driver for style {style!r}")
    if not (project / "assets" / "audio" / "sfx.wav").is_file():
        raise StyledRenderError("sound bed produced no assets/audio/sfx.wav")


def build_film(
    *,
    style: str,
    project_dir: Path,
    story_dir: Path,
) -> Path:
    """Assemble a runnable style project from the reference film + local story."""
    if not (story_dir / "story.json").is_file():
        raise StyledRenderError(f"story.json not found in {story_dir}")
    source = style_source(style)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, project_dir, dirs_exist_ok=True)
    _ensure_tools(project_dir, style)

    # hyperframes only serves the project dir → core + kit + story + narration land inside it
    _run(
        ["bash", str(lanshu_root() / "tools" / "sync.sh"), str(project_dir), style, str(story_dir)],
        env=_render_env(),
    )
    import json

    story = json.loads(
        re.search(
            r"window\.STORY = (.*);\s*$",
            (project_dir / "lib" / "story.js").read_text(encoding="utf-8"),
            re.S,
        ).group(1)
    )
    from hevi.providers.hyperframes.beat_generator import generate_beats_js

    beats_code = generate_beats_js(style, story)
    (project_dir / "beats.js").write_text(beats_code, encoding="utf-8")

    _stamp_durations(project_dir, story)
    _patch_puppeteer_sandbox(project_dir)
    _patch_sfxlib(project_dir)
    _patch_sfx_performed(project_dir)
    _run([sys.executable, str(lanshu_root() / "tools" / "fonts.py"), str(project_dir)], env=_render_env())
    _vendor_cdn(project_dir)
    _build_sfx(project_dir, style)
    return project_dir


def render_film(
    *,
    project_dir: Path,
    output_path: Path,
    fps: int = 30,
    quality: str = "looks",
    timeout_s: float = 1800.0,
) -> Path:
    binary = shutil.which("hyperframes")
    if not binary:
        raise StyledRenderError("hyperframes CLI not found on PATH")
    project_dir = project_dir.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        binary,
        "render",
        str(project_dir),
        "-o",
        str(output_path),
        "-f",
        str(fps),
        "-q",
        quality,
        "--no-best-effort",
        "--quiet",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(project_dir), env=_render_env(), capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise StyledRenderError(f"hyperframes render timed out after {timeout_s:.0f}s") from exc
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-1200:] + (proc.stderr or "")[-1200:]
        raise StyledRenderError(f"hyperframes render failed ({proc.returncode}):\n{tail}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise StyledRenderError(f"hyperframes render wrote nothing: {output_path}")
    return output_path


async def render_styled_film(
    *,
    style: str,
    output_path: Path | str,
    story_dir: Path | str,
    fps: int = 30,
    quality: str = "looks",
    timeout_s: float = 1800.0,
) -> Path:
    """Full build + render for one style.  Blocking work runs in a thread."""
    import asyncio

    out = Path(output_path)
    project = out.parent / f".{out.stem}_styled"
    return await asyncio.to_thread(
        _render_sync,
        style=style,
        output_path=out,
        project_dir=project,
        story_dir=Path(story_dir),
        fps=fps,
        quality=quality,
        timeout_s=timeout_s,
    )


def _render_sync(
    *,
    style: str,
    output_path: Path,
    project_dir: Path,
    story_dir: Path,
    fps: int,
    quality: str,
    timeout_s: float,
) -> Path:
    build_film(style=style, project_dir=project_dir, story_dir=story_dir)
    return render_film(
        project_dir=project_dir,
        output_path=output_path,
        fps=fps,
        quality=quality,
        timeout_s=timeout_s,
    )


__all__ = [
    "STYLES",
    "StyledRenderError",
    "build_film",
    "lanshu_root",
    "render_film",
    "render_styled_film",
    "style_source",
]
