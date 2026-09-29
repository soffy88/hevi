"""Shared helpers for P5.3 end-to-end drivers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.recipes import load_all_recipes


def make_library() -> RecipeLibrary:
    lib = RecipeLibrary()
    for r in load_all_recipes():
        lib.register(r)
    return lib


def make_beats(count: int, *, profile: str, intent: str, phase: str = "DEVELOPMENT") -> list[VisualBeat]:
    """Create real VisualBeats for an E2E run."""
    beats: list[VisualBeat] = []
    for i in range(count):
        start = float(i) * 3.0
        beats.append(VisualBeat(
            beat_id=f"e2e-b{i}",
            timeline_start_s=start,
            timeline_end_s=start + 3.0,
            narration_span=f"narration segment {i}",
            intent_id=intent,
            shot_role=["ESTABLISH", "EXPLAIN", "REVEAL", "DETAIL", "COMPARE", "PAYOFF"][i % 6],
            narrative_phase=phase if i < count - 1 else "PAYOFF",
            information_gain="NEW_DETAIL",
            importance=0.5 + (i / count) * 0.5,
        ))
    return beats


def render_video(beats: list[VisualBeat], out_dir: Path, *, renderer: str = "html_gsap") -> Path:
    """Render a real video through the P5.2 HTML/GSAP renderer."""
    from hevi.renderers import register_all_renderers
    from hevi.renderers.base import RendererId, RenderPlan, render
    register_all_renderers()
    rid = RendererId.HTML_GSAP if renderer == "html_gsap" else RendererId.FFMPEG
    paths: list[Path] = []
    for i, beat in enumerate(beats):
        plan = RenderPlan(
            shot_id=beat.beat_id, duration_s=2.0, fps=24, width=960, height=540,
            caption_text=beat.narration_span,
            semantic_intent=beat.intent_id or "EXPLAIN",
        )
        result = render(plan, out_dir / f"shot_{i}", renderer_id=rid)
        assert result.outcome.value == "OK", result.reason
        paths.append(Path(result.output_path))
    # Concatenate into one video
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / "final.mp4"
    if len(paths) == 1:
        return paths[0]
    list_file = out_dir / "concat.txt"
    list_file.write_text("".join(f"file '{p}'\n" for p in paths), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(final)],
        check=True, capture_output=True,
    )
    return final


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(proc.stdout.strip())
