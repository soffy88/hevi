"""Export Gemini Omni Flash / Google Flow prompt pack (omodul).

Reads a source text + duration + aspect + art style + optional director
overlay, plans the 5-stage heartbeat structure, compiles one complete
standalone prompt per ~10s clip (each repeating the full continuity
lock block verbatim), and writes two files:

- ``pack.md``  — human-readable director proposal + global continuity
  block + per-clip prompts + stitching guide + voice/music continuity
  note + optional post-production overlay suggestions.
- ``pack.json`` — machine-readable equivalent.

The module is **pure file generation**: it never calls any API.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.dirstyle.oprim_impl import get_style
from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import compile_prompt
from hevi.layer4_legacy.dirstyle.oskill_impl.heartbeat5 import (
    HeartbeatPlan,
    plan_heartbeat5,
)

__all__ = ["FlowPack", "export_flow_pack"]


@dataclass
class FlowPack:
    """Result of exporting a Flow prompt pack."""

    pack_dir: str
    pack_md_path: str
    pack_json_path: str
    plan: HeartbeatPlan
    art_style_id: str
    director_style_id: str | None
    aspect: str
    narration_lang: str
    clip_prompts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_dir": self.pack_dir,
            "pack_md_path": self.pack_md_path,
            "pack_json_path": self.pack_json_path,
            "plan": self.plan.to_dict(),
            "art_style_id": self.art_style_id,
            "director_style_id": self.director_style_id,
            "aspect": self.aspect,
            "narration_lang": self.narration_lang,
            "clip_prompts": self.clip_prompts,
        }


def _aspect_rules(aspect: str, art_style_id: str) -> str:
    """Aspect-specific composition rules for the given art style."""
    style = get_style(art_style_id)
    comp_rules = style.composition.get("rules", [])
    if aspect == "9:16":
        v916 = style.vertical_9x16
        if v916.get("mode") == "recompose":
            return "; ".join(v916.get("rules", []))
        for r in comp_rules:
            if r.startswith("9:16"):
                return r
        return "; ".join(comp_rules)
    for r in comp_rules:
        if r.startswith("16:9"):
            return r
    return "; ".join(comp_rules)


def _compile_clip_prompt(
    art_style_id: str,
    director_style_id: str | None,
    scene: str,
    aspect: str,
) -> dict[str, Any]:
    """Compile one standalone clip prompt via the dirstyle compiler."""
    if director_style_id:
        return compile_prompt(
            director_style_id,
            scene=scene,
            aspect=aspect,
            target="video",
            art_style=art_style_id,
        )
    return compile_prompt(
        art_style_id,
        scene=scene,
        aspect=aspect,
        target="video",
    )


def _global_continuity_block(
    art_style_id: str,
    director_style_id: str | None,
    aspect: str,
    duration_s: float,
    narration_lang: str,
) -> dict[str, Any]:
    """Global continuity block repeated in every clip prompt."""
    style = get_style(art_style_id)
    return {
        "art_style_id": art_style_id,
        "director_style_id": director_style_id,
        "aspect": aspect,
        "target_duration_s": duration_s,
        "clip_count": max(1, round(duration_s / 10.0)),
        "character_dna": style.character_dna,
        "line_weight": style.line_weight,
        "palette_words": ", ".join(style.palette_wordlist),
        "composition_aspect": _aspect_rules(aspect, art_style_id),
        "rhythm": f"avg {style.rhythm['avg_shot_s']}s/clip, {style.rhythm['cut_rule']}",
        "narration_lang": narration_lang,
        "negative_constraints": list(style.negative),
    }


def _build_clip_beats(narration: str) -> dict[str, str]:
    """Three timed beats [0-3s][3-7s][7-10s] for a clip."""
    sentences = [s.strip() for s in re.split(r"(?<=[。！？…!?.])\s+", narration) if s.strip()]
    if len(sentences) >= 3:
        return {"0-3s": sentences[0], "3-7s": sentences[1], "7-10s": sentences[2]}
    if len(sentences) == 2:
        return {"0-3s": sentences[0], "3-7s": sentences[1], "7-10s": sentences[1]}
    if len(sentences) == 1:
        return {"0-3s": sentences[0], "3-7s": sentences[0], "7-10s": sentences[0]}
    return {"0-3s": narration, "3-7s": narration, "7-10s": narration}


def _stitching_guide(clip_count: int) -> list[str]:
    """Stitching guide lines for assembling the N clips."""
    return [
        "1. Generate each clip independently in Google Flow using the standalone prompt above.",
        f"2. Name clips in sequence: clip_00.mp4, clip_01.mp4, ..., clip_{clip_count - 1:02d}.mp4.",
        "3. Check first/last frame continuity at every cut: the ending visual state of clip i must match the opening state of clip i+1.",
        "4. Stitch with ffmpeg concat (no re-encode):",
        "   ffmpeg -f concat -safe 0 -i filelist.txt -c copy output.mp4",
        "   where filelist.txt contains:",
        "     file 'clip_00.mp4'",
        "     file 'clip_01.mp4'",
        "     ...",
        "5. Or use Hevi's video-assemble step to concatenate the clip files in order.",
        "6. Keep audio (voiceover + BGM) continuous across cuts; if using separate audio, crossfade 0.5s at each junction.",
    ]


def _voice_music_continuity(narration_lang: str) -> list[str]:
    """Voice and music continuity note."""
    lang_note = "Chinese (default for Hevi users)" if narration_lang == "zh" else "English"
    return [
        f"Voiceover language: {lang_note}.",
        "One frozen narrator voice profile for the whole video (identity/age, accent, timbre, register, resonance, texture, delivery, pace, recording treatment). Do not change voice per clip.",
        "Voiceover is audio-only: no speech bubbles, no dialogue boxes, no visible text in the generated clips.",
        "BGM: clip 1 establishes the musical theme; clips 2-N continue the identical BGM seamlessly (same tempo, instrumentation, mood).",
        "SFX: synchronized crisp SFX on physical character actions.",
        "Word-count scaling: ~20-25 English words or ~45-60 Chinese characters per 10s clip.",
    ]


def _optional_overlays(plan: HeartbeatPlan) -> list[dict[str, str]]:
    """Optional post-production text overlays (kept OUT of prompts)."""
    overlays: list[dict[str, str]] = []
    for seg in plan.segments:
        if seg.stage_index == 4:
            overlays.append({
                "clip": f"clip_{seg.clip_index:02d}",
                "text": "你的选择是什么？",
                "placement": "interface-safe lower band",
            })
    return overlays


def _format_clip_prompt_md(
    clip_index: int,
    prompt: dict[str, Any],
    beats: dict[str, str],
    narration: str,
    global_block: dict[str, Any],
) -> str:
    """Format one standalone clip prompt as markdown."""
    lines = [
        f"### Clip {clip_index:02d}",
        "",
        "**Output specification**: ~10 seconds, target 720p, 24 FPS, synchronized audio.",
        "",
        "**Global continuity lock (repeated verbatim)**:",
        f"- Character DNA: {global_block['character_dna']}",
        f"- Line weight: {global_block['line_weight']}",
        f"- Palette: {global_block['palette_words']}",
        f"- Composition ({global_block['aspect']}): {global_block['composition_aspect']}",
        f"- Rhythm: {global_block['rhythm']}",
        f"- Negative: {', '.join(global_block['negative_constraints'])}",
        "",
        "**Timed visual beats**:",
        f"- [0-3s]: {beats['0-3s']}",
        f"- [3-7s]: {beats['3-7s']}",
        f"- [7-10s]: {beats['7-10s']}",
        "",
        f"**Audio voiceover (audio-only, no speech bubbles)**: \"{narration}\"",
        "",
        "**Compiled generation prompt**:",
        "```",
        prompt["positive"],
        "```",
        "",
        f"**Negative prompt**: {prompt['negative']}",
        "",
    ]
    return "\n".join(lines)


def export_flow_pack(
    *,
    source_text: str,
    duration_s: float,
    aspect: str = "9:16",
    art_style: str = "stickman_1a_light",
    director_style: str | None = None,
    voice: str | None = None,
    narration_lang: str = "zh",
    output_dir: str | Path | None = None,
) -> FlowPack:
    """Export a Gemini Omni Flash / Google Flow prompt pack.

    Args:
        source_text: Source narration/article text (Chinese or English).
        duration_s: Target duration in seconds.
        aspect: "9:16" or "16:9".
        art_style: stickman art-style id (e.g. "stickman_1a_light").
        director_style: optional director overlay id (e.g. "wes_anderson").
        voice: optional voice profile name (recorded in pack, not used).
        narration_lang: "zh" (default) or "en".
        output_dir: output directory (default: output/dirstyle_e2e/flow_pack_<duration>s).

    Returns:
        FlowPack with paths to pack.md and pack.json.

    Raises:
        ValueError: if duration_s <= 0 or aspect invalid.
    """
    if duration_s <= 0:
        raise ValueError("duration_s must be > 0")
    if aspect not in ("9:16", "16:9"):
        raise ValueError("aspect must be '9:16' or '16:9'")

    plan = plan_heartbeat5(
        source_text=source_text,
        duration_s=duration_s,
        narration_lang=narration_lang,
    )

    global_block = _global_continuity_block(
        art_style_id=art_style,
        director_style_id=director_style,
        aspect=aspect,
        duration_s=duration_s,
        narration_lang=narration_lang,
    )

    clip_prompts: list[dict[str, Any]] = []
    for seg in plan.segments:
        beats = _build_clip_beats(seg.narration)
        prompt = _compile_clip_prompt(
            art_style_id=art_style,
            director_style_id=director_style,
            scene=seg.narration,
            aspect=aspect,
        )
        clip_prompts.append({
            "clip_index": seg.clip_index,
            "stage_zh": seg.stage_zh,
            "stage_en": seg.stage_en,
            "narration": seg.narration,
            "beats": beats,
            "prompt": prompt,
            "global_continuity_lock": global_block,
        })

    if output_dir is None:
        output_dir = Path("output/dirstyle_e2e") / f"flow_pack_{int(duration_s)}s"
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    md_path = out_path / "pack.md"
    md_content = _render_pack_md(
        plan=plan,
        global_block=global_block,
        clip_prompts=clip_prompts,
        art_style=art_style,
        director_style=director_style,
        aspect=aspect,
        narration_lang=narration_lang,
        voice=voice,
    )
    md_path.write_text(md_content, encoding="utf-8")

    json_path = out_path / "pack.json"
    json_content = {
        "pack_version": 1,
        "art_style": art_style,
        "director_style": director_style,
        "aspect": aspect,
        "duration_s": duration_s,
        "narration_lang": narration_lang,
        "voice": voice,
        "global_continuity_lock": global_block,
        "plan": plan.to_dict(),
        "clip_prompts": clip_prompts,
        "stitching_guide": _stitching_guide(plan.clip_count),
        "voice_music_continuity": _voice_music_continuity(narration_lang),
        "optional_overlays": _optional_overlays(plan),
    }
    json_path.write_text(
        json.dumps(json_content, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return FlowPack(
        pack_dir=str(out_path),
        pack_md_path=str(md_path),
        pack_json_path=str(json_path),
        plan=plan,
        art_style_id=art_style,
        director_style_id=director_style,
        aspect=aspect,
        narration_lang=narration_lang,
        clip_prompts=clip_prompts,
    )


def _render_pack_md(
    *,
    plan: HeartbeatPlan,
    global_block: dict[str, Any],
    clip_prompts: list[dict[str, Any]],
    art_style: str,
    director_style: str | None,
    aspect: str,
    narration_lang: str,
    voice: str | None,
) -> str:
    """Render the human-readable pack.md content."""
    lines: list[str] = []

    lines.append("# Gemini Omni Flash / Google Flow Prompt Pack")
    lines.append("")
    lines.append(f"- Art style: `{art_style}`")
    if director_style:
        lines.append(f"- Director overlay: `{director_style}`")
    lines.append(f"- Aspect ratio: {aspect}")
    lines.append(f"- Target duration: {plan.duration_s:.0f}s ({plan.clip_count} clips)")
    lines.append(f"- Narration language: {narration_lang}")
    if voice:
        lines.append(f"- Voice profile: {voice}")
    lines.append(f"- Hook window: {plan.hook_window[0]:.0f}-{plan.hook_window[1]:.0f}s")
    lines.append("")

    lines.append("## Director Proposal")
    lines.append("")
    lines.append(f"**Title**: {plan.title}")
    lines.append(f"**Core message**: {plan.topic}")
    lines.append("**Narrative arc**: 5-stage heartbeat (黄金钩子 → 打破常识 → 拉出内幕 → 真相揭秘 → 升华互动)")
    lines.append("")

    lines.append("## Global Continuity Block")
    lines.append("")
    lines.append(f"- **Character DNA**: {global_block['character_dna']}")
    lines.append(f"- **Line weight**: {global_block['line_weight']}")
    lines.append(f"- **Palette**: {global_block['palette_words']}")
    lines.append(f"- **Composition ({aspect})**: {global_block['composition_aspect']}")
    lines.append(f"- **Rhythm**: {global_block['rhythm']}")
    lines.append(f"- **Negative constraints**: {', '.join(global_block['negative_constraints'])}")
    lines.append("")

    lines.append("## Clip Prompts")
    lines.append("")
    for cp in clip_prompts:
        lines.append(_format_clip_prompt_md(
            clip_index=cp["clip_index"],
            prompt=cp["prompt"],
            beats=cp["beats"],
            narration=cp["narration"],
            global_block=global_block,
        ))
        lines.append("")

    lines.append("## Stitching Guide")
    lines.append("")
    for line in _stitching_guide(plan.clip_count):
        lines.append(line)
    lines.append("")

    lines.append("## Voice & Music Continuity")
    lines.append("")
    for line in _voice_music_continuity(narration_lang):
        lines.append(f"- {line}")
    lines.append("")

    lines.append("## Optional Post-Production Overlays")
    lines.append("")
    lines.append("(Kept OUT of the generation prompts — add these in post-production only.)")
    lines.append("")
    for ov in _optional_overlays(plan):
        lines.append(f"- {ov['clip']}: \"{ov['text']}\" — {ov['placement']}")
    lines.append("")

    return "\n".join(lines)
