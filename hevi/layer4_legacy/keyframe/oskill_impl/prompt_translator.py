"""Chinese shot description to English SD prompt translator oskill.

Combines rule-based phrase synthesis with verbatim character card appearance tokens.
Optional LLM rewriting with immediate fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Any

from hevi.layer4_legacy.keyframe.oprim_impl.character_card import CharacterCard
from hevi.prompt.style_presets import (
    DEFAULT_KEYFRAME_STYLE,
    KEYFRAME_STYLE_PRESETS,
    get_keyframe_style,
)

logger = logging.getLogger(__name__)

# Deterministic domain dictionary for classical / narrative fiction
_TRANSLATION_MAP: list[tuple[re.Pattern[str], str]] = [
    # Characters & roles (used only when not overridden by character cards)
    (re.compile(r"仙人|神仙"), "celestial immortal sage"),
    (re.compile(r"宾客|客人|众客"), "gathered guests in traditional robes"),
    # Attire & Objects & Props
    (re.compile(r"拂尘"), "white horsetail whisk"),
    (re.compile(r"斧头|利斧|采樵|砍柴"), "carrying woodchopping iron axe and bundles of firewood"),
    (re.compile(r"酒壶|酒杯|玉液|共饮|畅饮|同饮|延客"), "ceramic wine jug and celadon cups on banquet table"),
    (re.compile(r"明月|圆月|皓月|月亮|纸月|剪纸|月华|月光"), "a large radiant glowing bright full moon on the wall, luminous lunar sphere shining brightly, soft moonlight glow"),
    (re.compile(r"筷子|飞起"), "mystical floating bamboo chopsticks in mid-air"),
    # Settings & Environment
    (re.compile(r"崂山|深山|崇山"), "lofty misty Mount Laoshan, ancient pines and craggy peaks"),
    (re.compile(r"道观|观宇|禅房|大殿"), "ancient mountain Taoist monastery courtyard, timber architecture"),
    (re.compile(r"石壁|墙壁|砖墙|面壁|坚壁"), "solid ancient granite stone wall"),
    (re.compile(r"穿墙|破壁|穿壁"), "mystically phasing through solid stone wall without collision"),
    (re.compile(r"月下|夜色|月夜|深夜"), "moonlit night, soft luminous lunar glow, deep blue sky"),
    (re.compile(r"烛光|灯火"), "warm flickering candlelight, dramatic atmospheric shadows"),
    (re.compile(r"宴饮|痛饮|畅饮"), "convivial ancient Chinese evening banquet"),
    (re.compile(r"归途|下山|离去"), "mountain path leading down the misty valley"),
    # Shots & Angles
    (re.compile(r"特写"), "close-up portrait shot, detailed facial expression"),
    (re.compile(r"全景|远景"), "wide establishing cinematic shot, epic landscape"),
    (re.compile(r"中景"), "medium shot"),
]

# Required subject keyword verification map: (Chinese regex, English token, English desc)
REQUIRED_SUBJECT_MAP: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"明月|圆月|皓月|月亮|月华"), "moon", "a radiant glowing bright full moon"),
    (re.compile(r"斧头|利斧|采樵|砍柴"), "axe", "woodchopping axe"),
    (re.compile(r"石壁|墙壁|穿壁|坚壁"), "wall", "solid ancient granite stone wall"),
    (re.compile(r"酒壶|酒杯|玉液|共饮|宴"), "wine", "ceramic wine jug and cups banquet"),
    (re.compile(r"王生|书生"), "scholar", "young handsome Chinese scholar in Hanfu"),
    (re.compile(r"老道长|老道|师父"), "Taoist", "venerable elderly Taoist master with white beard"),
]

DEFAULT_STYLE = (
    "cinematic lighting, ancient Chinese Xianxia aesthetic, 8k masterpiece, detailed atmosphere, sharp focus"
)
DEFAULT_NEGATIVE = (
    "modern clothing, glasses, cars, distorted anatomy, extra limbs, bad face, watermark, text, low quality, blurry"
)


def resolve_style_preset(style: str | None) -> dict[str, object]:
    """Return a normalized keyframe style preset dict (never raises).

    Known preset names (and None/"") map to their preset. An unknown non-empty
    string is treated as legacy raw style tags: it keeps the default anime prefix
    off, uses the raw string as tags, and adds no extra negative.
    """
    if style and style not in KEYFRAME_STYLE_PRESETS:
        return {
            "name": DEFAULT_KEYFRAME_STYLE,
            "prompt_prefix": "",
            "style_tags": style,
            "negative": "",
            "photoreal": False,
            "legacy_tags": style,
        }
    name = style or DEFAULT_KEYFRAME_STYLE
    preset = dict(get_keyframe_style(name))
    preset["name"] = name
    preset["legacy_tags"] = ""
    return preset


def _resolve_style(style: str | None) -> tuple[str, str, str, bool]:
    """Resolve a style argument into (prompt_prefix, style_tags, style_negative, is_photoreal).

    - None / "" / a known preset name -> that keyframe style preset (default anime_guofeng).
    - Any other non-empty string is treated as legacy raw style tags (backward compatible).
    """
    preset = resolve_style_preset(style)
    return (
        str(preset.get("prompt_prefix") or ""),
        str(preset.get("style_tags") or ""),
        str(preset.get("negative") or ""),
        bool(preset.get("photoreal")),
    )


def _try_llm_translate(zh_text: str, timeout_s: float = 2.0) -> str | None:
    """Attempt fast translation via local/free omniroute or local LLM if enabled."""
    if os.environ.get("HEVI_USE_LLM", "0") != "1":
        return None

    api_url = os.environ.get("HEVI_OMNIROUTE_URL", "http://127.0.0.1:20128/v1/chat/completions")
    payload = {
        "model": os.environ.get("HEVI_LLM_MODEL", "auto/best-fast"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Translate the Chinese shot description into a concise English Stable Diffusion prompt. "
                    "Focus only on visual elements, character appearances, setting, and lighting. Output prompt only."
                ),
            },
            {"role": "user", "content": zh_text},
        ],
        "max_tokens": 80,
    }
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if content and len(content) > 10:
                return content
    except Exception as exc:
        logger.debug("LLM prompt rewrite bypassed: %s", exc)
    return None


def _rule_translate_scene(text: str) -> list[str]:
    tokens: list[str] = []
    for pattern, eng in _TRANSLATION_MAP:
        if pattern.search(text):
            if eng not in tokens:
                tokens.append(eng)
    return tokens


def zh_shot_to_sd_prompt(
    shot: Any,
    *,
    character_cards: list[CharacterCard] | dict[str, CharacterCard] | None = None,
    style: str | None = DEFAULT_KEYFRAME_STYLE,
    director_style: str | None = None,
) -> tuple[str, str]:
    """Convert Chinese shot details into English Stable Diffusion prompt & negative prompt.

    Args:
        shot: dict or KernelShot with visual_desc, visible_chars, environment, etc.
        character_cards: character dossier registry to pull locked appearance tokens.
        style: keyframe style preset name (``anime_guofeng`` default, ``ink``,
            ``flat_comic``, ``photoreal``). An unknown non-empty string is treated as
            raw legacy style tags; ``None`` selects the default anime style.

    Returns:
        (prompt_en, negative_prompt)
    """
    if isinstance(shot, str):
        visual_desc = shot
        visible_chars: list[str] = []
        env = ""
        focal_char = None
    elif isinstance(shot, dict):
        visual_desc = str(shot.get("visual_desc") or shot.get("script") or shot.get("text") or "")
        visible_chars = [str(c) for c in (shot.get("visible_chars") or shot.get("characters") or [])]
        env = str(shot.get("environment") or shot.get("location") or "")
        focal_char = shot.get("primary_char") or shot.get("focal_char")
    else:
        visual_desc = str(getattr(shot, "visual_desc", "") or getattr(shot, "script", ""))
        visible_chars = [str(c) for c in getattr(shot, "visible_chars", [])]
        env = str(getattr(shot, "environment", "") or getattr(shot, "location", ""))
        focal_char = getattr(shot, "primary_char", None) or getattr(shot, "focal_char", None)

    full_zh = f"{env} {visual_desc}".strip()

    style_prefix, style_tags, style_negative, is_photoreal = _resolve_style(style)
    
    # If director_style provided, append director visual language
    if director_style:
        from hevi.layer4_legacy.dirstyle.oprim_impl import get_style as _get_dir_style
        from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import _strip_vague as _strip
        try:
            dir_style = _get_dir_style(director_style)
            # Build director-specific positive tokens
            dir_pos_parts = [
                f"{dir_style.lens_aspect['focal']}, {dir_style.lens_aspect['aspect']} frame",
                "; ".join(dir_style.composition["rules"]),
                "; ".join(dir_style.lighting["rules"]),
                "; ".join(dir_style.color["rules"]),
                "; ".join(dir_style.motion["rules"]),
            ]
            dir_pos = _strip(", ".join(dir_pos_parts))
            # Append to existing positive prompt
            style_prefix = f"{style_prefix}, {dir_pos}" if style_prefix else dir_pos
            # Add director's negative to style_negative
            if dir_style.negative:
                extra_neg = ", ".join(dir_style.negative)
                style_negative = f"{style_negative}, {extra_neg}" if style_negative else extra_neg
        except ValueError:
            pass  # unknown director style, skip
    base_negative = f"{DEFAULT_NEGATIVE}, {style_negative}" if style_negative else DEFAULT_NEGATIVE

    # 1. Resolve character card lookup
    card_lookup: dict[str, CharacterCard] = {}
    if character_cards:
        if isinstance(character_cards, dict):
            card_lookup = character_cards
        else:
            for card in character_cards:
                card_lookup[card.name] = card
                card_lookup[card.id] = card
                for a in card.aliases:
                    card_lookup[a] = card

    # Infer focal character if not explicitly provided
    if not focal_char:
        if "王生" in visible_chars or "王生" in full_zh or "书生" in full_zh:
            # If Wang Sheng is active or solo
            if "老道长坐蒲团上" in full_zh:
                focal_char = "老道长"
            else:
                focal_char = "王生"
        elif "老道长" in visible_chars or "道长" in full_zh or "老道" in full_zh:
            focal_char = "老道长"

    char_tokens: list[str] = []
    negative = base_negative

    # 2. Assign character tokens prioritizing focal character
    if focal_char == "王生":
        wang_card = card_lookup.get("王生")
        if wang_card and wang_card.appearance_en_tokens:
            char_tokens.append(f"{wang_card.appearance_en_tokens}, focused on the young Chinese scholar")
        for cname in visible_chars:
            if cname not in ("王生", "王七", "书生", "弟子"):
                other_card = card_lookup.get(cname)
                if other_card and other_card.appearance_en_tokens:
                    char_tokens.append(other_card.appearance_en_tokens)
        # If Wang Sheng is solo, forbid elderly / white beard in negative prompt
        if not any(c in visible_chars for c in ["老道长", "宾客", "众人", "师父"]):
            negative = f"{base_negative}, elderly, old man, white beard, white hair, grey hair, wrinkled face"
    elif focal_char == "老道长":
        dao_card = card_lookup.get("老道长")
        if dao_card and dao_card.appearance_en_tokens:
            char_tokens.append(f"{dao_card.appearance_en_tokens}, focused on the venerable Taoist master")
        for cname in visible_chars:
            if cname not in ("老道长", "道长", "师父", "老道"):
                other_card = card_lookup.get(cname)
                if other_card and other_card.appearance_en_tokens:
                    char_tokens.append(other_card.appearance_en_tokens)
    else:
        # Check if this is a scene shot like the Moon
        is_moon_shot = any(pattern.search(full_zh) for pattern, k, _ in REQUIRED_SUBJECT_MAP if k == "moon")
        if is_moon_shot:
            char_tokens.append("a large radiant glowing bright full moon on the wall, luminous lunar sphere shining brightly, soft moonlight beam")
            negative = f"{base_negative}, person, human, character, man, woman"
        else:
            # Normal multi-character or generic
            for char_name in visible_chars:
                card = card_lookup.get(char_name)
                if card and card.appearance_en_tokens and card.appearance_en_tokens not in char_tokens:
                    char_tokens.append(card.appearance_en_tokens)

    # 3. Translate scene elements and enforce required subject keywords
    llm_en = _try_llm_translate(full_zh)
    if llm_en:
        scene_tokens = [llm_en]
    else:
        scene_tokens = _rule_translate_scene(full_zh)
        if not scene_tokens and not char_tokens:
            scene_tokens = ["ancient Chinese mountain setting, atmospheric drama"]

    # Ensure required subject tokens are present in scene
    for pattern, subj_key, subj_desc in REQUIRED_SUBJECT_MAP:
        if pattern.search(full_zh):
            # Check if keyword already appears in char_tokens or scene_tokens
            combined_txt = " ".join(char_tokens + scene_tokens).lower()
            if subj_key.lower() not in combined_txt:
                scene_tokens.append(subj_desc)

    # 4. Assemble prompt parts
    prompt_parts: list[str] = []
    if style_prefix:
        prompt_parts.append(style_prefix)
    prompt_parts.extend(char_tokens)
    prompt_parts.extend(scene_tokens)
    if style_tags:
        prompt_parts.append(style_tags)

    # Dedup preserving order and trim excess
    deduped: list[str] = []
    for part in prompt_parts:
        clean = part.strip().rstrip(",")
        if clean and clean not in deduped:
            deduped.append(clean)

    prompt_en = ", ".join(deduped)
    return prompt_en, negative
