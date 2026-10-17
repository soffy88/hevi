"""Post-render self-checks built on the vendored Anatomy scripts.

Every check here runs a *real* headless Chromium (CPU, SwiftShader) against the
page that was just built, through the upstream scripts:

======================  ===================================================
``scripts/capture.mjs`` one still of the card, console + readout reported
``scripts/drive.mjs``   a scripted session and a tiled contact sheet
``scripts/lines.mjs``   every texture line end must land on something
``scripts/turn-check.mjs`` 3D order / pops / line ends / kit fidelity
======================  ===================================================

A failure raises :class:`AnatomyVerifyError` with the script that failed, its
exit code and the tail of its output, so the renderer never ships a figure that
did not pass its own checks.  Nothing here is mocked: no check passes unless the
script printed its success line.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.capabilities.anatomy_explainer.chrome import chrome_env
from hevi.capabilities.errors import CapabilityError

__all__ = [
    "AnatomyVerifyError",
    "VerifyReport",
    "check_console",
    "check_fidelity",
    "check_lines",
    "check_turn",
    "contact_sheet",
    "capture_still",
    "image_stats",
    "scripts_dir",
    "turning_builder",
]

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[2]
ANATOMY_DIR = REPO_ROOT / "third_party" / "anatomy"
SCRIPTS = ANATOMY_DIR / "scripts"

#: The Hevi 3D figure module (exports ``T`` and ``P`` for ``--fidelity``).
TURNING_BUILDER = PACKAGE_DIR / "turn_windmill.mjs"


class AnatomyVerifyError(CapabilityError):
    """A post-render check failed; the message names the script and why."""


def scripts_dir() -> Path:
    if not SCRIPTS.is_dir():  # pragma: no cover - vendored tree is committed
        raise AnatomyVerifyError(f"Anatomy scripts missing: {SCRIPTS}")
    return SCRIPTS


def turning_builder() -> Path:
    if not TURNING_BUILDER.is_file():  # pragma: no cover
        raise AnatomyVerifyError(f"3D builder missing: {TURNING_BUILDER}")
    return TURNING_BUILDER


@dataclass
class VerifyReport:
    """What the checks measured, written next to the render as JSON."""

    checks: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, **values: Any) -> None:
        self.checks[name] = values

    def as_dict(self) -> dict[str, Any]:
        return {"passed": True, "checks": self.checks}

    def write(self, path: Path) -> Path:
        path.write_text(json.dumps(self.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return path


def _tail(text: str, lines: int = 24) -> str:
    rows = [row for row in (text or "").strip().splitlines() if row.strip()]
    return "\n".join(rows[-lines:])


def run_script(
    name: str,
    args: list[str],
    *,
    label: str,
    timeout: float = 900.0,
    expect: tuple[str, ...] = (),
) -> str:
    """Run ``third_party/anatomy/scripts/<name>`` and return its stdout.

    ``expect`` lists substrings that must appear in the output; a missing one is
    a failure too (a script that exits 0 without saying it checked anything did
    not check anything).
    """
    script = scripts_dir() / name
    if not script.is_file():
        raise AnatomyVerifyError(f"{label}: script missing at {script}")
    cmd = ["node", str(script), *args]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=chrome_env())
    except subprocess.TimeoutExpired as exc:
        raise AnatomyVerifyError(f"{label} timed out after {timeout:.0f}s: {' '.join(cmd)}") from exc
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0:
        raise AnatomyVerifyError(
            f"{label} failed (exit {res.returncode}) via {script.name}:\n{_tail(out)}\n"
            f"command: {' '.join(cmd)}"
        )
    missing = [token for token in expect if token not in out]
    if missing:
        raise AnatomyVerifyError(
            f"{label} did not report {missing} via {script.name}:\n{_tail(out)}"
        )
    return res.stdout


def check_console(stdout: str, *, label: str) -> None:
    """capture.mjs and drive.mjs print ``console: clean`` when the page is quiet."""
    for row in stdout.splitlines():
        if row.startswith("console:") and "clean" not in row:
            raise AnatomyVerifyError(f"{label}: page raised console errors or exceptions:\n{row}")
        if row.startswith("Exception") or row.startswith("Uncaught"):
            raise AnatomyVerifyError(f"{label}: page raised an exception:\n{row}")


def image_stats(path: Path, *, background: tuple[int, int, int] | None = None) -> dict[str, Any]:
    """Measure a PNG: size, how much is not background, and how many colours.

    ``background`` defaults to the image's own dominant colour, so the check
    works for the kid-blue plates and for the kit's light/dark cards alike.
    """
    try:
        from PIL import Image  # local import: the renderer already depends on Pillow
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise AnatomyVerifyError(f"image_stats needs Pillow and numpy: {exc}") from exc
    if not path.is_file():
        raise AnatomyVerifyError(f"expected a screenshot at {path}, nothing was written")
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        arr = np.asarray(rgb)
    if background is None:
        flat = arr.reshape(-1, 3)
        colours, counts = np.unique(flat, axis=0, return_counts=True)
        background = tuple(int(v) for v in colours[int(counts.argmax())])
    diff = np.abs(arr.astype("float32") - np.array(background, dtype="float32"))
    ink = np.any(diff > 24, axis=2)
    stats = {
        "path": str(path),
        "background": list(background),
        "width": int(arr.shape[1]),
        "height": int(arr.shape[0]),
        "ink_ratio": round(float(ink.mean()), 5),
        "colours": int(len(np.unique(arr.reshape(-1, 3), axis=0))),
    }
    if arr.shape[0] < 80 or arr.shape[1] < 80:
        raise AnatomyVerifyError(f"screenshot {path} is only {arr.shape[1]}x{arr.shape[0]} px")
    if stats["ink_ratio"] < 0.01:
        raise AnatomyVerifyError(f"screenshot {path} is blank: ink ratio {stats['ink_ratio']}")
    if stats["colours"] < 8:
        raise AnatomyVerifyError(f"screenshot {path} has only {stats['colours']} colours")
    return stats


def capture_still(html: Path, out_png: Path, *, wait: int = 900, width: int = 1440) -> dict[str, Any]:
    """``capture.mjs``: one still of the card, console checked, image measured."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    stdout = run_script(
        "capture.mjs",
        [str(html), "--out", str(out_png), "--wait", str(wait), "--width", str(width), "--scale", "1"],
        label="Anatomy capture",
        timeout=300,
        expect=("saved ", "console:"),
    )
    check_console(stdout, label="Anatomy capture")
    if "scrolls sideways: yes" in stdout:
        raise AnatomyVerifyError("Anatomy capture: the card scrolls sideways at this width")
    readout = ""
    for row in stdout.splitlines():
        if row.startswith("clip ") and "readout" in row:
            readout = row
    stats = image_stats(out_png)
    stats["capture"] = readout
    return stats


def contact_sheet(html: Path, out_png: Path, *, every: int = 160, count: int = 8, reduced: bool = True) -> dict[str, Any]:
    """``drive.mjs``: a tiled contact sheet of ``count`` frames ``every`` ms apart."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    actions = json.dumps([["wait", 400], ["sheet", str(out_png), every, count]])
    args = [str(html), actions, "--width", "1440", "--height", "1200"]
    if reduced:
        args.append("--reduced")
    stdout = run_script("drive.mjs", args, label="Anatomy contact sheet", timeout=600, expect=("sheet ", "console:"))
    check_console(stdout, label="Anatomy contact sheet")
    if f"{count} frames" not in stdout:
        raise AnatomyVerifyError(f"Anatomy contact sheet: expected {count} frames, got:\n{_tail(stdout, 8)}")
    stats = image_stats(out_png)
    stats["frames"] = count
    stats["sheet"] = stdout.strip().splitlines()[0]
    return stats


def check_lines(html: Path, *, out_png: Path | None = None, timeout: float = 600.0) -> dict[str, Any]:
    """``lines.mjs``: every texture line end must land on something."""
    args = [str(html), "--wait", "900"]
    if out_png is not None:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        args += ["--out", str(out_png)]
    stdout = run_script("lines.mjs", args, label="Anatomy floating-line check", timeout=timeout, expect=("line ends:",))
    row = next((line for line in stdout.splitlines() if line.startswith("line ends:")), "")
    # upstream prints "line ends: 0 of 56 ends on 9 lines float"
    if not row or " 0 of " not in f" {row}":
        raise AnatomyVerifyError(f"Anatomy floating-line check: {row}\n{_tail(stdout)}")
    check_console(stdout, label="Anatomy floating-line check")
    return {"report": row.strip()}


def check_turn(
    html: Path,
    *,
    order: bool = False,
    pops: bool = False,
    out_dir: Path | None = None,
    timeout: float = 1200.0,
) -> dict[str, Any]:
    """``turn-check.mjs``: 3D order, pops and line ends at many angles."""
    args = [str(html), "--lines"]
    if order:
        args.append("--order")
    if pops:
        args.append("--pops")
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        args += ["--out", str(out_dir)]
    stdout = run_script("turn-check.mjs", args, label="Anatomy 3D turn check", timeout=timeout, expect=("turn check passed",))
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return {"report": lines}


def check_fidelity(build_mjs: Path, *, angles: str | None = None, timeout: float = 900.0) -> dict[str, Any]:
    """``turn-check.mjs <build.mjs> --fidelity``: live shapes against the kit."""
    args = [str(build_mjs), "--fidelity"]
    if angles:
        args += ["--angles", angles]
    stdout = run_script("turn-check.mjs", args, label="Anatomy 3D kit fidelity", timeout=timeout, expect=("fidelity passed",))
    rows = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not any("fails as it should" in row for row in rows):
        raise AnatomyVerifyError("Anatomy 3D kit fidelity: the planted control did not fail:\n" + _tail(stdout))
    return {"report": rows}


def build_turning_page(
    out_dir: Path,
    *,
    aspect: str = "16:9",
    theme: str = "light",
    verify: bool = True,
    audit: bool = False,
    quick: bool = True,
    timeout: float = 1200.0,
) -> tuple[Path, str]:
    """Run the Hevi 3D builder. Returns ``(html_path, stdout)``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html = out_dir / f"anatomy_turning_windmill_{aspect.replace(':', 'x')}.html"
    args = [
        "node",
        str(turning_builder()),
        "--aspect",
        aspect,
        "--theme",
        theme,
        "--out",
        str(html),
    ]
    if verify:
        args.append("--verify")
    if audit:
        args += ["--audit"]
        if quick:
            args.append("--quick")
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise AnatomyVerifyError(f"3D builder timed out after {timeout:.0f}s: {' '.join(args)}") from exc
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0:
        raise AnatomyVerifyError(f"3D builder failed (exit {res.returncode}):\n{_tail(out)}")
    if audit and "turn audit passed" not in out:
        raise AnatomyVerifyError(f"3D orbit audit did not pass:\n{_tail(out)}")
    if not html.is_file():
        raise AnatomyVerifyError(f"3D builder exited 0 but wrote no page at {html}")
    return html, res.stdout


def env_summary() -> dict[str, str]:
    """The toolchain a render used, for the report."""
    from hevi.capabilities.anatomy_explainer.chrome import chrome_version

    ffmpeg = os.environ.get("HEVI_FFMPEG", "/home/soffy/.local/bin/ffmpeg")
    ffmpeg = ffmpeg if Path(ffmpeg).exists() else "ffmpeg"
    return {
        "chrome": chrome_version(),
        "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
        "ffmpeg": ffmpeg,
        "tmpdir": tempfile.gettempdir(),
    }
