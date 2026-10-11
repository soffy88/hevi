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

logger = logging.getLogger(__name__)

# Deterministic domain dictionary for classical / narrative fiction
_TRANSLATION_MAP: list[tuple[re.Pattern[str], str]] = [
    # Characters & roles
    (re.compile(r"老道长|老道士|道长|老道|师父|师尊"), "venerable elderly Taoist master with long white beard"),
    (re.compile(r"道士|道人"), "Taoist priest in grey robes"),
    (re.compile(r"王生|书生|秀才|文人"), "young Chinese scholar in Hanfu robes"),
    (re.compile(r"徒弟|弟子|门徒"), "young Taoist disciple"),
    (re.compile(r"仙人|神仙"), "celestial immortal sage"),
    (re.compile(r"宾客|客人|众客"), "gathered guests in traditional robes"),
    # Age & Appearance
    (re.compile(r"白须|白胡子|白发|苍老"), "long silver white beard and hair, weathered wise face"),
    (re.compile(r"青年|年轻"), "youthful handsome countenance"),
    (re.compile(r"中年"), "middle-aged mature look"),
    # Attire & Objects
    (re.compile(r"道袍|法袍"), "flowing traditional grey Taoist robe"),
    (re.compile(r"汉服|青衫|蓝袍"), "classic blue Hanfu silk robe"),
    (re.compile(r"拂尘"), "white horsetail whisk"),
    (re.compile(r"斧头|采樵|砍柴"), "carrying woodchopping axe and bundles of firewood"),
    (re.compile(r"酒壶|酒杯|玉液"), "ceramic wine jug and celadon cups"),
    (re.compile(r"剪纸|月亮|纸月"), "round glowing paper moon pinned on wall"),
    (re.compile(r"筷子|飞起"), "mystical floating bamboo chopsticks in mid-air"),
    # Settings & Environment
    (re.compile(r"崂山|深山|崇山"), "lofty misty Mount Laoshan, ancient pines and craggy peaks"),
    (re.compile(r"道观|观宇|禅房|大殿"), "ancient mountain Taoist monastery courtyard, timber architecture"),
    (re.compile(r"石壁|墙壁|砖墙"), "solid ancient granite stone wall"),
    (re.compile(r"穿墙|破壁|穿壁"), "phasing magically through solid stone wall without collision"),
    (re.compile(r"月下|夜色|月夜|深夜"), "moonlit night, soft luminous lunar glow, deep blue sky"),
    (re.compile(r"烛光|灯火"), "warm flickering candlelight, dramatic atmospheric shadows"),
    (re.compile(r"宴饮|痛饮|畅饮"), "convivial ancient Chinese evening banquet"),
    (re.compile(r"归途|下山|离去"), "mountain path leading down the misty valley"),
    # Shots & Angles
    (re.compile(r"特写"), "close-up portrait shot, detailed facial expression"),
    (re.compile(r"全景|远景"), "wide establishing cinematic shot, epic landscape"),
    (re.compile(r"中景"), "medium shot"),
]

DEFAULT_STYLE = (
    "cinematic lighting, ancient Chinese Xianxia aesthetic, 8k masterpiece, detailed atmosphere, sharp focus"
)
DEFAULT_NEGATIVE = (
    "modern clothing, glasses, cars, distorted anatomy, extra limbs, bad face, watermark, text, low quality, blurry"
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
    style: str | None = None,
) -> tuple[str, str]:
    """Convert Chinese shot details into English Stable Diffusion prompt & negative prompt.

    Args:
        shot: dict or KernelShot with visual_desc, visible_chars, environment, etc.
        character_cards: character dossier registry to pull locked appearance tokens.
        style: optional visual style tags.

    Returns:
        (prompt_en, negative_prompt)
    """
    if isinstance(shot, str):
        visual_desc = shot
        visible_chars: list[str] = []
        env = ""
    elif isinstance(shot, dict):
        visual_desc = str(shot.get("visual_desc") or shot.get("script") or shot.get("text") or "")
        visible_chars = [str(c) for c in (shot.get("visible_chars") or shot.get("characters") or [])]
        env = str(shot.get("environment") or shot.get("location") or "")
    else:
        visual_desc = str(getattr(shot, "visual_desc", "") or getattr(shot, "script", ""))
        visible_chars = [str(c) for c in getattr(shot, "visible_chars", [])]
        env = str(getattr(shot, "environment", "") or getattr(shot, "location", ""))

    full_zh = f"{env} {visual_desc}".strip()

    # 1. Resolve character card tokens
    char_tokens: list[str] = []
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

    for char_name in visible_chars:
        card = card_lookup.get(char_name)
        if card and card.appearance_en_tokens:
            if card.appearance_en_tokens not in char_tokens:
                char_tokens.append(card.appearance_en_tokens)

    # 2. Check LLM translation option
    llm_en = _try_llm_translate(full_zh)
    if llm_en:
        scene_tokens = [llm_en]
    else:
        # Rule-based fallback translation
        scene_tokens = _rule_translate_scene(full_zh)
        if not scene_tokens:
            scene_tokens = ["ancient Chinese mountain setting, atmospheric drama"]

    # 3. Assemble prompt parts
    prompt_parts: list[str] = []
    if char_tokens:
        prompt_parts.extend(char_tokens)
    prompt_parts.extend(scene_tokens)

    style_tag = style if style is not None else DEFAULT_STYLE
    if style_tag:
        prompt_parts.append(style_tag)

    # Dedup preserving order
    deduped: list[str] = []
    for part in prompt_parts:
        clean = part.strip().rstrip(",")
        if clean and clean not in deduped:
            deduped.append(clean)

    prompt_en = ", ".join(deduped)
    return prompt_en, DEFAULT_NEGATIVE
