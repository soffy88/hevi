"""Chinese visual description to English SD prompt builder for comic panels.

Ensures character appearance consistency tokens and style tokens are applied.

3O Pillar: oskill.comicnarr_prompt_builder
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Any

from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicStyle

logger = logging.getLogger(__name__)

# Domain translation dictionary for comic and graphic novel visual elements
_COMIC_KEYWORD_MAP: list[tuple[re.Pattern[str], str]] = [
    # Cat & pet specifics
    (re.compile(r"橘猫|猫咪|猫"), "cute chubby orange tabby cat with expressive eyes"),
    (re.compile(r"爪子|肉垫"), "soft fluffy paws touching the surface"),
    (re.compile(r"水杯|杯子"), "clear glass water tumbler falling and splashing water"),
    (re.compile(r"书桌|桌沿|桌面"), "wooden study desk edge, clean indoor room"),
    (re.compile(r"打碎|摔碎|落地"), "glass shattering on the floor with dynamic motion lines"),
    (re.compile(r"探出|张望|低头"), "peeking head curiously downward over table edge"),
    (re.compile(r"推倒|推|拨弄"), "playfully nudging object off the table with paw"),
    (re.compile(r"玩具|纸团"), "rolling crumpled paper ball toy on the floor"),
    (re.compile(r"主人|惊呼|跑进"), "surprised person standing in doorway of cozy room"),
    (re.compile(r"阳光|客厅|收纳"), "sunlight streaming into modern tidy living room"),
    (re.compile(r"捕食|猎物|本能"), "curious predatory focus, dilated pupils, hunting instinct"),
    # Classical Chinese specifics
    (re.compile(r"书生|成名|读书人"), "young ancient Chinese scholar in cyan Hanfu robe"),
    (re.compile(r"蟋蟀|促织|微虫"), "splendid shiny golden-green fighting cricket insect on stone"),
    (re.compile(r"宫廷|宣德|大殿"), "ancient Ming dynasty imperial palace hall, incense smoke"),
    (re.compile(r"荒草|古庙|破庙"), "ancient overgrown stone temple ruins, wild autumn grass"),
    (re.compile(r"巫婆|占卜|老妇"), "mysterious elderly fortune teller in ragged robes with divining herbs"),
    (re.compile(r"神符|图|画卷"), "glowing mystical calligraphy talisman parchment scroll"),
    (re.compile(r"大佛寺|后山|松林"), "misty mountain path behind Buddhist monastery, craggy pine trees"),
    (re.compile(r"竹筒|竹笼|捉"), "delicate traditional bamboo tube cricket carrier"),
    (re.compile(r"青花瓷盆|磁盆|饲养"), "exquisite blue and white antique porcelain dish on desk"),
    (re.compile(r"决斗|角斗|振翅"), "two fighting crickets in porcelain arena, intense action lines"),
    (re.compile(r"古道|苍茫|落叶"), "lonely ancient mountain road with drifting autumn leaves"),
    # Compositions & Angles
    (re.compile(r"特写"), "close-up panel shot, highly detailed focus"),
    (re.compile(r"远景|全景"), "wide establishing comic panel shot, epic environment"),
    (re.compile(r"俯视|俯瞰"), "high angle view looking down"),
    (re.compile(r"仰视"), "low angle dynamic perspective"),
    (re.compile(r"阳光|光线"), "soft atmospheric lighting rays"),
    (re.compile(r"夜|月夜|深夜"), "moonlit night scene, deep shadows"),
]


def _try_llm_translate(text_zh: str, timeout_s: float = 2.0) -> str | None:
    """Attempt fast translation via local omniroute if configured."""
    if os.environ.get("HEVI_USE_LLM", "1") == "0":
        return None

    api_url = os.environ.get("HEVI_OMNIROUTE_URL", "http://127.0.0.1:20128/v1/chat/completions")
    payload = {
        "model": os.environ.get("HEVI_LLM_MODEL", "auto/best-fast"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Translate the Chinese comic scene description into concise visual English tokens for Stable Diffusion. "
                    "Focus strictly on concrete visual objects, actions, and framing. Output comma-separated English tokens only."
                ),
            },
            {"role": "user", "content": text_zh},
        ],
        "max_tokens": 60,
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
            if content and len(content) > 8:
                return content
    except Exception as exc:
        logger.debug("LLM prompt translation bypassed: %s", exc)
    return None


def _rule_translate(text_zh: str) -> list[str]:
    tokens: list[str] = []
    for pattern, eng in _COMIC_KEYWORD_MAP:
        if pattern.search(text_zh):
            if eng not in tokens:
                tokens.append(eng)
    if not tokens:
        tokens.append("expressive dynamic comic panel scene, clean composition")
    return tokens


def build_scene_prompt(
    *,
    visual_desc_zh: str,
    character_desc_en: str,
    style: ComicStyle,
    use_llm: bool = True,
) -> tuple[str, str]:
    """Build English prompt and negative prompt for a comic panel.

    Combines:
      1. Fixed protagonist tokens (guarantees character consistency across panels)
      2. Scene-specific English translation
      3. Style template tokens
    """
    clean_desc = (visual_desc_zh or "").strip()

    # 1. Translate scene description
    llm_en = _try_llm_translate(clean_desc) if use_llm else None
    if llm_en:
        scene_tokens = [llm_en]
    else:
        scene_tokens = _rule_translate(clean_desc)

    # 2. Assemble components
    prompt_parts: list[str] = []

    # Lead with protagonist if defined
    if character_desc_en:
        prompt_parts.append(character_desc_en.strip())

    prompt_parts.extend(scene_tokens)

    if style.style_tokens:
        prompt_parts.append(style.style_tokens.strip())

    # Deduplicate while preserving sequence
    deduped: list[str] = []
    for p in prompt_parts:
        clean = p.strip().rstrip(",")
        if clean and clean not in deduped:
            deduped.append(clean)

    prompt_en = ", ".join(deduped)
    negative_prompt = style.negative_prompt

    return prompt_en, negative_prompt


__all__ = [
    "build_scene_prompt",
]
