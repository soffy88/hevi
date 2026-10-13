"""Prompt compiler for director-style (oskill, pure functions).

Formula: [six dimensions] + [scene/action] + [camera_move] + [negative].
Director names NEVER appear in the prompt output.
"""
from __future__ import annotations

from typing import Any

from hevi.layer4_legacy.dirstyle.oprim_impl.models import DirectorStyle

__all__ = ["compile_prompt"]

# Words that must never appear in the positive prompt — vague hype words
# replaced by concrete lens/light/motion/color decisions already captured.
_VAGUE_WORDS: list[str] = [
    "电影感", "cinematic", "大片感", "epic", "masterpiece", "高级感",
    "氛围感", "beautiful", "beautifully", "stunning", "gorgeous",
    "cinematic lighting", "dreamy", "moody", "atmospheric",
    "photorealistic", "photo", "realistic", "hyperrealistic",
    "史诗感", "质感", "大片质感", "电影质感", "大片即视感",
    "8k masterpiece", "masterpiece",
]


def _strip_vague(text: str) -> str:
    out = text
    for w in _VAGUE_WORDS:
        out = out.replace(w, "")
    # clean up double commas and trailing commas/spaces
    while ",," in out:
        out = out.replace(",,", ",")
    out = out.strip(" ,")
    return out


def compile_prompt(
    style_id: str,
    scene: str,
    action: str | None = None,
    camera_move: str | None = None,
    genre: str | None = None,
    aspect: str = "9:16",
    lang: str = "zh",
    target: str = "video",
    *,
    style: DirectorStyle | None = None,
    keyframe_style: str | None = None,
    director_style_id: str | None = None,
    art_style: str | None = None,
) -> dict[str, Any]:
    """Compile a prompt for the given director style + scene.

    Args:
        style_id: id of the style (e.g. "wong_kar_wai").
        scene: Chinese scene description.
        action: optional action description.
        camera_move: optional camera move from the camera-move-library.
        genre: optional genre hint.
        aspect: target canvas aspect ("9:16" default).
        lang: "zh" or "en" — affects provenance language.
        target: "keyframe" or "video".
        style: pre-loaded DirectorStyle; if None, falls back to lookup.
        keyframe_style: keyframe preset name (triggers anime_safe filtering).
        director_style_id: overlay director style id on top of the art style.
        art_style: overlay stickman art-style id (character DNA / line / palette);
            when set, this overrides style_id for the art dimension.  Conflict
            resolution: art style wins on character / line / palette; the
            director style only contributes composition / color / motion / rhythm.

    Returns:
        {positive, negative, camera, aspect_note, style_id, provenance}
    """
    if style is None:
        from hevi.layer4_legacy.dirstyle.oprim_impl import get_style
        style = get_style(style_id)

    # ---- Art-style overlay: switch style to art_style when provided ----
    # art_style is orthogonal to director_style_id: the art_style governs the
    # character/line/palette dimension while the director_style_id contributes
    # composition/color/motion/rhythm only (see the stickman branch below).
    director_style_id_eff = director_style_id or style_id
    if art_style and art_style != style_id:
        from hevi.layer4_legacy.dirstyle.oprim_impl import get_style as _gs
        style = _gs(art_style)
        director_style_id_eff = style_id  # the outer id becomes the director

    # ---- Stickman art-style branch ----
    # For stickman styles the character DNA anchor must be verbatim-frozen at
    # the start of the positive prompt. The regular six-dimension prose would
    # duplicate / contradict the DNA lock, so we take a shorter path.
    if style.is_stickman():
        dna = style.character_dna.strip()
        lw = style.line_weight.strip()
        pw = ", ".join(style.palette_wordlist)
        # F3 fix: Only include composition rules matching the target aspect
        comp_rules = [
            r for r in style.composition.get("rules", [])
            if aspect in r or not any(ratio in r for ratio in ["9:16", "16:9"])
        ]
        comp = "; ".join(comp_rules)
        rhythm = f"avg {style.rhythm['avg_shot_s']}s/clip, {style.rhythm['cut_rule']}"

        pos_parts: list[str] = []
        provenance: list[str] = []
        for label, val in (
            ("character_dna", dna),
            ("line_weight", lw),
            ("palette_words", pw),
            ("composition", comp),
            ("rhythm", rhythm),
        ):
            if val:
                pos_parts.append(val)
                provenance.append(f"{label}: {val}")
        # optional director overlay (composition / color / motion / rhythm only)
        if director_style_id_eff and director_style_id_eff != style.id:
            from hevi.layer4_legacy.dirstyle.oprim_impl import get_style as _gs
            try:
                d_style = _gs(director_style_id_eff)
                if d_style.id != style.id:
                    # F3 fix: Only include composition rules matching the target aspect
                    comp_rules_filtered = [
                        r for r in d_style.composition.get("rules", [])
                        if aspect in r or not any(ratio in r for ratio in ["9:16", "16:9"])
                    ]
                    overlay = [
                        "; ".join(comp_rules_filtered),
                        "; ".join(d_style.color.get("rules", [])),
                        "; ".join(d_style.motion.get("rules", [])),
                        f"avg {d_style.rhythm['avg_shot_s']}s/shot, {d_style.rhythm['cut_rule']}",
                    ]
                    # F3: Filter out colors that conflict with art style palette
                    # Only include director color rules that don't list specific colors
                    # (those are handled by the art style's palette_wordlist)
                    color_rules = d_style.color.get("rules", [])
                    # Remove rules that are just color lists (keep composition/lightness rules)
                    color_rules_filtered = [
                        r for r in color_rules
                        if not any(c in r for c in ["pink", "yellow", "green", "blue", "gold", "red"])
                    ]
                    if color_rules_filtered:
                        overlay[1] = "; ".join(color_rules_filtered)
                    overlay = [o for o in overlay if o]
                    if overlay:
                        pos_parts.append(", ".join(overlay))
                        provenance.append(f"director_overlay: {director_style_id_eff}")
                    extra_neg = [n for n in d_style.negative if n not in style.negative]
                    negative_extra = extra_neg
                else:
                    negative_extra = []
            except ValueError:
                negative_extra = []
        else:
            negative_extra = []
        if scene and scene.strip():
            pos_parts.append(scene.strip())
            provenance.append(f"scene: {scene.strip()}")
        if action and action.strip():
            pos_parts.append(action.strip())
            provenance.append(f"action: {action.strip()}")
        if camera_move and camera_move.strip():
            pos_parts.append(camera_move.strip())
            provenance.append(f"camera_move: {camera_move.strip()}")

        positive = _strip_vague(", ".join(p for p in pos_parts if p.strip()))
        negative = ", ".join(list(style.negative) + negative_extra)
        return {
            "positive": positive,
            "negative": negative,
            "camera": camera_move or "; ".join(style.motion["rules"]),
            "aspect_note": style.lens_aspect["aspect"],
            "style_id": style_id,
            "provenance": provenance,
            "keyframe_style": keyframe_style,
            "character_dna": dna,
            "director_style_id": director_style_id_eff,
            "art_style": art_style,
        }

    pos_parts: list[str] = []
    provenance: list[str] = []

    def add(label: str, value: str) -> None:
        v = value.strip()
        if v:
            pos_parts.append(v)
            provenance.append(f"{label}: {v}")

    # Six dimensions
    add("lens_aspect",
        f"{style.lens_aspect['focal']}, {style.lens_aspect['aspect']} frame")
    add("composition", "; ".join(style.composition["rules"]))
    add("lighting", "; ".join(style.lighting["rules"]))
    add("color", "; ".join(style.color["rules"]))
    add("motion", "; ".join(style.motion["rules"]))
    add("rhythm",
        f"avg {style.rhythm['avg_shot_s']}s/shot, {style.rhythm['cut_rule']}")

    # Required signatures
    sig_text = "; ".join(
        s["en"] for s in style.signature if s.get("required"))
    add("signature", sig_text)

    # Scene / action / genre
    if scene:
        add("scene", scene.strip())
    if action:
        add("action", action.strip())
    if genre:
        add("genre", genre.strip())

    # Camera move
    if camera_move:
        add("camera_move", camera_move.strip())

    # Build positive
    positive = ", ".join(p for p in pos_parts if p.strip())
    positive = _strip_vague(positive)

    # Filter conflict words from anime_safe when combined with a keyframe style
    if keyframe_style:
        import re
        conflict_words = style.anime_safe.get("conflict_words", [])
        for cw in conflict_words:
            if cw.lower() in positive.lower():
                positive = re.sub(re.escape(cw), "", positive, flags=re.IGNORECASE)
        for old, new in style.anime_safe.get("rewrites", {}).items():
            if old.lower() in positive.lower():
                positive = re.sub(re.escape(old), new, positive, flags=re.IGNORECASE)
        positive = _strip_vague(positive)

    # Negative (never include director name)
    negative = ", ".join(style.negative)

    # Aspect note
    if style.is_wide_aspect():
        if aspect == "9:16":
            mode = style.vertical_9x16.get("mode", "letterbox")
            if mode == "native":
                aspect_note = "Native 9:16 recompose"
            else:
                aspect_note = f"Letterboxed to 9:16 ({mode})"
        else:
            aspect_note = style.lens_aspect["aspect"]
    else:
        aspect_note = style.lens_aspect["aspect"]

    # Keyframe truncation: keep signature block verbatim first, then pad up to ~250 chars
    if target == "keyframe":
        # Preserve the signature block intact (semicolon-joined)
        keep: list[str] = []
        if sig_text:
            keep.append(sig_text)
        # then add non-signature tokens, preserve order
        sig_set = set(t.strip() for t in sig_text.replace(";", ",").split(",") if t.strip())
        for part in positive.split(","):
            stripped = part.strip()
            if stripped and stripped not in keep and stripped not in sig_set:
                keep.append(stripped)
            if len(keep) >= 5:
                break
        positive = ", ".join(keep)
        if len(positive) > 250:
            positive = positive[:247] + "..."

    return {
        "positive": positive,
        "negative": negative,
        "camera": camera_move or "; ".join(style.motion["rules"]),
        "aspect_note": aspect_note,
        "style_id": style_id,
        "provenance": provenance,
        "keyframe_style": keyframe_style,
    }
