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
    overlays: list[dict[str, str]] = field(default_factory=list)

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


def _strip_voice_prefix(value: str) -> str:
    """Drop a leading "Voice profile:" so md rendering never doubles it (F5)."""
    if value.startswith("Voice profile:"):
        return value[len("Voice profile:") :].strip()
    return value


def _clean_token_list(text: str) -> str:
    """Split a comma list, drop empty tokens, rejoin with ", " (F3).

    Guards against the ``"broken line weight, , 3D humanoid"`` empty-token
    artefact that appears when a filtered word leaves a dangling comma.
    """
    parts = [p.strip() for p in text.split(",")]
    parts = [p for p in parts if p]
    return ", ".join(parts)


def _camera_from_beats(beats: dict[str, str]) -> str:
    """Derive a vertical-only camera description from a clip's beats (F3).

    The camera line is a shot list built from this clip's own beats (which
    already carry vertical framing + pose transitions), so it is specific to
    the clip and never contains lateral / pan / arc wording.
    """
    return f"{beats['0-3s']}; {beats['3-7s']}; {beats['7-10s']}"


def _compile_clip_prompt(
    art_style_id: str,
    director_style_id: str | None,
    scene: str,
    aspect: str,
    palette_override: list[str] | None = None,
    beats: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compile one standalone clip prompt via the dirstyle compiler.

    F3 fixes:
    - ``scene`` is deliberately NOT forwarded to the compiler, so Chinese
      narration never leaks into the generation prompt (prompt_en must be
      CJK-free; prompt_zh must not echo the narration).
    - ``palette_override`` pins the compiled prompt's colour words to the
      lock block's Palette so the two colour-word sets match exactly (<=3).
    - ``camera`` is replaced with a vertical-only shot list derived from the
      clip's beats (never the style's unrelated lateral motion rules).
    """
    prompt = compile_prompt(
        director_style_id or art_style_id,
        scene="",
        aspect=aspect,
        target="video",
        art_style=art_style_id if director_style_id else None,
        palette_override=palette_override,
    )

    # F5: strip residual realism wording from both prompts.
    realism_words = [
        "photorealistic",
        "photorealism",
        "realistic",
        "realism",
        "photo-real",
        "hyperrealistic",
        "cgi",
        "3d render",
        "photoreal",
        "写实",
        "照片级",
        "照片般",
    ]
    for word in realism_words:
        prompt["positive"] = prompt["positive"].replace(word, "")
        prompt["negative"] = prompt["negative"].replace(word, "")

    # F3: normalise the comma lists (drop the empty-token artefact) and pin
    # the camera to a vertical shot list derived from this clip's beats.
    prompt["positive"] = _clean_token_list(prompt["positive"])
    prompt["negative"] = _clean_token_list(prompt["negative"])
    if beats:
        prompt["camera"] = _camera_from_beats(beats)
    return prompt


def _get_director_palette(director_style_id: str | None) -> list[str]:
    """Get top-3 accent colors from director style palette as words."""
    from hevi.layer4_legacy.dirstyle.oprim_impl import get_style

    if not director_style_id:
        return []
    try:
        style = get_style(director_style_id)
        palette = style.color.get("palette", [])
        # Take first 3 colors, convert hex to descriptive words
        color_words = []
        word_map = {
            "#f7c5d4": "pastel pink",
            "#e8b87b": "mustard yellow",
            "#a8d8c0": "mint green",
            "#92c5e8": "sky blue",
            "#f4e4c1": "cream",
            "#2f6f5e": "teal green",
            "#4fb08a": "seafoam",
            "#e75480": "magenta",
            "#f2c94c": "warm gold",
        }
        for hex_color in palette[:3]:
            word = word_map.get(hex_color, hex_color)
            color_words.append(word)
        return color_words
    except ValueError:
        return []


def _resolve_palette(art_style: str, director_style_id: str | None) -> list[str]:
    """Resolve final palette: director accents take priority, art style as fallback.

    Rule: Art style defines base (background/line color), director style provides
    up to 3 accent colors. When director is specified, use its top-3 palette.
    When no director, use art style's default palette.
    """
    from hevi.layer4_legacy.dirstyle.oprim_impl import get_style

    if director_style_id:
        director_accents = _get_director_palette(director_style_id)
        if director_accents:
            return director_accents

    # Fallback: use art style's palette
    art_style_obj = get_style(art_style)
    return art_style_obj.palette_wordlist[:3]


def _strip_hex_rgb(text: str) -> str:
    """Remove hex colors and RGB notation from text."""
    import re

    # Remove hex colors like #f7c5d4
    text = re.sub(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", "", text)
    # Remove RGB notation like rgb(123, 45, 67)
    text = re.sub(r"rgb\s*\([^)]+\)", "", text)
    # Clean up
    text = text.replace(",,", ",").strip(", ")
    return text


def _global_continuity_block(
    art_style_id: str,
    director_style_id: str | None,
    aspect: str,
    duration_s: float,
    narration_lang: str,
    voice: str | None = None,
) -> dict[str, Any]:
    """Global continuity block repeated verbatim in every clip prompt.

    Contains the full frozen character DNA, line weight, palette,
    aspect-specific composition, rhythm, narrator voice profile and
    negative constraints.  No "same character" shortcuts.
    """
    style = get_style(art_style_id)
    # F5 fix: Voice profile must start with "Voice profile:" and be a specific frozen value
    if style.voice_profile:
        voice_profile = style.voice_profile
    elif voice:
        voice_profile = voice
    elif narration_lang == "zh":
        voice_profile = (
            "Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。"
        )
    else:
        voice_profile = (
            "Voice profile: English female, approx 30 years old, warm and clear, "
            "moderate pace ~4 words/sec, close-mic dry vocal, no reverb."
        )
    # Resolve palette: art style base + director accents (max 3)
    palette_words = _resolve_palette(art_style_id, director_style_id)
    return {
        "art_style_id": art_style_id,
        "director_style_id": director_style_id,
        "aspect": aspect,
        "target_duration_s": duration_s,
        "clip_count": max(1, round(duration_s / 10.0)),
        "character_dna": style.character_dna,
        "line_weight": style.line_weight,
        "palette_words": ", ".join(palette_words),
        "composition_aspect": _aspect_rules(aspect, art_style_id),
        "rhythm": f"avg {style.rhythm['avg_shot_s']}s/clip, {style.rhythm['cut_rule']}",
        "voice_profile": voice_profile,
        "narration_lang": narration_lang,
        "negative_constraints": list(style.negative),
    }


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
            overlays.append(
                {
                    "clip": f"clip_{seg.clip_index:02d}",
                    "text": "你的选择是什么？",
                    "placement": "interface-safe lower band",
                }
            )
    return overlays


def _format_clip_prompt_md(
    clip_index: int,
    prompt: dict[str, Any],
    beats: dict[str, str],
    narration: str,
    global_block: dict[str, Any],
    first_frame: str = "",
    last_frame: str = "",
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
        f"- Voice profile: {_strip_voice_prefix(global_block['voice_profile'])}",
        f"- Negative: {', '.join(global_block['negative_constraints'])}",
        "",
        f"**First frame:** {first_frame}",
        f"**Last frame:** {last_frame}",
        "",
        "**Timed visual beats**:",
        f"- [0-3s]: {beats['0-3s']}",
        f"- [3-7s]: {beats['3-7s']}",
        f"- [7-10s]: {beats['7-10s']}",
        "",
        f'**Audio voiceover (audio-only, no speech bubbles)**: "{narration}"',
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
        min_chars_per_clip=45,
    )

    # F7: Ensure core message is not empty
    if not plan.topic or not plan.topic.strip():
        # Extract a core message from the source text (first sentence or summary)
        sentences = [s.strip() for s in re.split(r"[。！？]", source_text) if s.strip()]
        plan.topic = sentences[0] if sentences else "Narrative about the source topic"

    global_block = _global_continuity_block(
        art_style_id=art_style,
        director_style_id=director_style,
        aspect=aspect,
        duration_s=duration_s,
        narration_lang=narration_lang,
        voice=voice,
    )

    clip_prompts: list[dict[str, Any]] = []
    for seg in plan.segments:
        # F1: canonical, per-clip distinct visual beats from the heartbeat plan.
        beats = dict(seg.action_beats)
        prompt = _compile_clip_prompt(
            art_style_id=art_style,
            director_style_id=director_style,
            scene=seg.narration,
            aspect=aspect,
            palette_override=global_block["palette_words"].split(", "),
            beats=beats,
        )
        clip_prompts.append(
            {
                "clip_index": seg.clip_index,
                "stage_zh": seg.stage_zh,
                "stage_en": seg.stage_en,
                "narration": seg.narration,
                "beats": beats,
                "prompt": prompt,
                "global_continuity_lock": global_block,
            }
        )

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
        overlays=_optional_overlays(plan),
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
        # F5: avoid "Voice profile: Voice profile: ..." when the caller already
        # passed a value that carries the prefix.
        voice_line = voice
        if voice_line.startswith("Voice profile:"):
            voice_line = voice_line[len("Voice profile:") :].strip()
        lines.append(f"- Voice profile: {voice_line}")
    lines.append(f"- Hook window: {plan.hook_window[0]:.0f}-{plan.hook_window[1]:.0f}s")
    lines.append("")

    lines.append("## Director Proposal")
    lines.append("")
    lines.append(f"**Title**: {plan.title}")
    lines.append(f"**Core message**: {plan.topic}")
    lines.append(
        "**Narrative arc**: 5-stage heartbeat (黄金钩子 → 打破常识 → 拉出内幕 → 真相揭秘 → 升华互动)"
    )
    lines.append("")
    lines.append("## Segment Transitions (Continuity Handoff)")
    lines.append("")
    lines.append("| Clip | Opening Frame | Closing Frame | Handoff |")
    lines.append("|------|---------------|---------------|---------|")
    for seg in plan.segments:
        handoff = (
            "cut (opens the video)"
            if seg.clip_index == 0
            else "match-cut: previous closing frame == this opening frame"
        )
        lines.append(
            f"| Clip {seg.clip_index:02d} | {seg.visual_state_start} "
            f"| {seg.visual_state_end} | {handoff} |"
        )
    lines.append("")

    lines.append("## Global Continuity Block")
    lines.append("")
    lines.append(f"- **Character DNA**: {global_block['character_dna']}")
    lines.append(f"- **Line weight**: {global_block['line_weight']}")
    lines.append(f"- **Palette**: {global_block['palette_words']}")
    lines.append(f"- **Composition ({aspect})**: {global_block['composition_aspect']}")
    lines.append(f"- **Rhythm**: {global_block['rhythm']}")
    # F5: the lock-block value already carries the "Voice profile:" prefix, so
    # strip it here to avoid "Voice profile: Voice profile: ...".
    vp = global_block["voice_profile"]
    if vp.startswith("Voice profile:"):
        vp = vp[len("Voice profile:") :].strip()
    lines.append(f"- **Voice profile**: {vp}")
    lines.append(f"- **Negative constraints**: {', '.join(global_block['negative_constraints'])}")
    lines.append("")

    lines.append("## Clip Prompts")
    lines.append("")
    for cp in clip_prompts:
        seg = plan.segments[cp["clip_index"]]
        lines.append(
            _format_clip_prompt_md(
                clip_index=cp["clip_index"],
                prompt=cp["prompt"],
                beats=cp["beats"],
                narration=cp["narration"],
                global_block=global_block,
                first_frame=seg.visual_state_start,
                last_frame=seg.visual_state_end,
            )
        )
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
        lines.append(f'- {ov["clip"]}: "{ov["text"]}" — {ov["placement"]}')
    lines.append("")

    return "\n".join(lines)
