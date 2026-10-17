"""M1 分镜生成器 (namegen) — entry point.

Parses a story script (Huobao-style or Hevi drama/comic) and produces: a
storyboard JSON model, an SVG page, a PNG page, and a QC report.  Pure-Python
+ Pillow; fully deterministic per seed.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..common import write_json, sha256_file, RenderSize
from . import Script, Storyboard
from .generator import generate
from .export import render_svg, svg_to_png


def parse_script(doc: dict) -> Script:
    """Parse a Huobao/Hevi style script dict into a Script.

    Expected keys:
      title: str
      characters: list[str]
      beats: list[{speaker?, text, emotion?, action?, pose?, shot?,
                   bg_kind?, bg_ref?, camera_side?}]
    """
    title = doc.get("title", "")
    chars = doc.get("characters", [])
    beats = doc.get("beats", [])
    if not beats:
        # Allow a flatter "lines" form.
        beats = doc.get("lines", [])
    return Script.from_lines(title, chars, beats)


def run(doc: dict, *, aspect: str = "9:16", reading_direction: str = "rtl",
        seed: str = "manga", variation: float = 0.3, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    script = parse_script(doc)
    board = generate(script, aspect, reading_direction, seed, variation)

    model = board.model()
    model_path = out / "storyboard.json"
    write_json(model_path, model)

    svg = render_svg(board)
    svg_path = out / "storyboard.svg"
    svg_path.write_text(svg, encoding="utf-8")
    png_path = svg_to_png(svg, out / "storyboard.png")

    report = build_qc_report(board, model_path, svg_path, png_path)
    write_json(out / "qc_report.json", report)
    return {
        "storyboard": str(model_path),
        "svg": str(svg_path),
        "png": str(png_path),
        "report": report,
    }


def build_qc_report(board: Storyboard, model_path: Path, svg_path: Path,
                    png_path: Path) -> dict:
    """Build a QC report: axis, text-fidelity, read-order, byte hashes."""
    # text fidelity: every dialogue text equals a verbatim beat text
    verbatim_ok = all(
        (p.dialogue is None) or (p.dialogue["text"] == p.beat.text)
        for p in board.panels
    )
    # read order is a permutation 1..N
    orders = sorted(p.read_order for p in board.panels)
    read_order_ok = orders == list(range(1, len(board.panels) + 1))
    return {
        "aspect": board.aspect,
        "seed": board.seed,
        "panel_count": len(board.panels),
        "axis_violations": board.axis_violations,
        "axis_ok": len(board.axis_violations) == 0,
        "text_verbatim_ok": verbatim_ok,
        "read_order_ok": read_order_ok,
        "sha256": {
            "storyboard.json": sha256_file(model_path),
            "storyboard.svg": sha256_file(svg_path),
            "storyboard.png": sha256_file(png_path),
        },
    }
