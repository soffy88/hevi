"""Chinese visual description to English SD prompt builder for comic panels.

Key design rules (COMICNARR rework r2):
  * Concrete props / actions come FIRST so the diffusion model weights them.
  * The fixed protagonist tokens are appended AFTER the scene and only when the
    scene actually features the protagonist (decided from the Chinese visual
    description), so a scholar is not painted into an empty palace hall.
  * No colour-bleeding identity tokens (e.g. "emerald green eyes").

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

# Domain translation dictionary for comic and graphic novel visual elements.
# Order matters: earlier entries are emitted first in the prompt.
_COMIC_KEYWORD_MAP: list[tuple[re.Pattern[str], str]] = [
    # --- Props / actions first (must dominate the prompt) ---
    (re.compile(r"水杯|杯子"), "clear glass drinking cup on a wooden desk"),
    (re.compile(r"摔碎|打碎|应声落地|落地"), "shattering glass with splashing water and motion lines"),
    (re.compile(r"盯着|凝视|注视|看着"), "staring intently at the object in front"),
    (re.compile(r"书桌|桌沿|桌面|书案|桌案"), "wooden study desk, clean indoor room"),
    (re.compile(r"爪子|肉垫"), "soft fluffy paws"),
    (re.compile(r"推倒|推|拨弄"), "paw playfully nudging an object off the table"),
    (re.compile(r"玩具|纸团|笔筒|铅笔"), "small desk toy and rolling crumpled paper ball"),
    (re.compile(r"探出|张望|低头"), "peeking head curiously downward over the edge"),
    (re.compile(r"主人|惊呼|跑进"), "surprised owner standing in the doorway"),
    (re.compile(r"阳光|客厅|收纳|封闭柜"), "sunlight streaming into a tidy living room"),
    (re.compile(r"捕食|猎物|本能|扑击"), "focused predatory hunting instinct, dilated pupils"),
    # --- Classical Chinese story ---
    (re.compile(r"宫廷|宣德|殿堂|金碧辉煌"), "ancient Ming dynasty imperial palace hall, incense smoke"),
    (re.compile(r"官员|呈送"), "Ming dynasty court officials in ceremonial robes"),
    (re.compile(r"蟋蟀|促织|微虫|异虫"), "shiny golden-green fighting cricket insect on a stone"),
    (re.compile(r"书生|成名|读书人"), "young ancient Chinese scholar in a cyan Hanfu robe and scholar cap"),
    (re.compile(r"书斋|书房"), "traditional Chinese scholar's study"),
    (re.compile(r"竹笼|竹筒"), "traditional bamboo cricket carrier"),
    (re.compile(r"巫婆|占卜|老妇|蓍草"), "elderly fortune teller in ragged robes with divining herbs"),
    (re.compile(r"神符|纸帛|画卷|墨迹"), "mystical calligraphy talisman parchment scroll"),
    (re.compile(r"古庙|破庙|古刹|寺庙"), "ancient overgrown stone temple"),
    (re.compile(r"后山|松林|古松|丛冢"), "misty mountain path with craggy pine trees"),
    (re.compile(r"青花瓷盆|磁盆|饲养|蟹肉"), "blue and white antique porcelain dish on the desk"),
    (re.compile(r"角斗|决斗|振翅|斗盆"), "two fighting crickets in a porcelain arena, intense action lines"),
    (re.compile(r"古道|苍茫|落叶"), "lonely ancient mountain road with drifting autumn leaves"),
    # --- Three Kingdoms (草船借箭) ---
    (re.compile(r"赤壁|长江|江面|江心"), "Yangtze river at Red Cliffs, warships and fluttering banners"),
    (re.compile(r"战船|快船|船队|草船"), "ancient Chinese wooden warships and fast boats on the river"),
    (re.compile(r"军帐|帐中|帐内"), "military command tent with maps and war banners"),
    (re.compile(r"周瑜"), "Eastern Wu general in ornate lamellar armour"),
    (re.compile(r"诸葛亮|孔明|羽扇|纶巾|鹤氅"), "strategist with a white feather fan and crane-feather cloak"),
    (re.compile(r"军令状|令箭"), "military pledge document and command arrow"),
    (re.compile(r"草人"), "straw dummies packed along the boat sides"),
    (re.compile(r"大雾|浓雾|雾气|雾散"), "dense fog over the river"),
    (re.compile(r"擂鼓|呐喊|战鼓"), "soldiers beating war drums and shouting"),
    (re.compile(r"弓箭手|箭雨|羽箭|万箭|弓弩"), "archers loosing a storm of arrows"),
    (re.compile(r"曹军|曹操"), "Cao Cao's warships and archers"),
    (re.compile(r"天亮|黎明|日出"), "dawn breaking through the dispersing fog"),
    (re.compile(r"落日|夕阳"), "golden sunset over the river"),
    # --- Framing ---
    (re.compile(r"特写"), "close-up panel shot, highly detailed focus"),
    (re.compile(r"远景|全景"), "wide establishing comic panel shot, epic environment"),
    (re.compile(r"俯视|俯瞰"), "high angle view looking down"),
    (re.compile(r"仰视"), "low angle dynamic perspective"),
    (re.compile(r"夜|月夜|深夜"), "moonlit night scene, deep shadows"),
]

#: Generic fallback scene token when nothing matched.
_GENERIC_SCENE_TOKEN = "expressive dynamic comic panel scene, clean composition"

#: Cache so an unreachable free LLM is not probed once per scene.
_LLM_TRANSLATE_DISABLED = False


def _try_llm_translate(text_zh: str, timeout_s: float = 2.0) -> str | None:
    """Attempt fast translation via local omniroute if configured."""
    global _LLM_TRANSLATE_DISABLED
    if _LLM_TRANSLATE_DISABLED:
        return None
    if os.environ.get("HEVI_USE_LLM", "1") == "0":
        _LLM_TRANSLATE_DISABLED = True
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
    except Exception as exc:  # noqa: BLE001 - free channel is best-effort
        logger.debug("LLM prompt translation unavailable, using rules: %s", exc)
        _LLM_TRANSLATE_DISABLED = True
    return None


def _rule_translate(text_zh: str) -> list[str]:
    tokens: list[str] = []
    for pattern, eng in _COMIC_KEYWORD_MAP:
        if pattern.search(text_zh):
            if eng not in tokens:
                tokens.append(eng)
    if not tokens:
        tokens.append(_GENERIC_SCENE_TOKEN)
    return tokens


def _scene_features_character(visual_desc_zh: str, character_tokens: tuple[str, ...]) -> bool:
    """Return True when the visual description mentions the protagonist."""
    if not character_tokens:
        return False
    return any(tok and tok in visual_desc_zh for tok in character_tokens)


def build_scene_prompt(
    *,
    visual_desc_zh: str,
    character_desc_en: str,
    style: ComicStyle,
    character_tokens: tuple[str, ...] = (),
    use_llm: bool = True,
) -> tuple[str, str]:
    """Build English prompt and negative prompt for a comic panel.

    Order: scene props/action -> protagonist (only if featured) -> style tokens.
    """
    clean_desc = (visual_desc_zh or "").strip()

    # 1. Translate scene description (LLM if available, deterministic rules otherwise)
    llm_en = _try_llm_translate(clean_desc) if use_llm else None
    if llm_en:
        scene_tokens = [llm_en]
    else:
        scene_tokens = _rule_translate(clean_desc)

    # 2. Assemble components - scene first, protagonist only when featured.
    prompt_parts: list[str] = list(scene_tokens)

    if character_desc_en and _scene_features_character(clean_desc, character_tokens):
        prompt_parts.append(character_desc_en.strip())

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
