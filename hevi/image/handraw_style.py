"""Handraw-style numbered prompt library (yang0/handraw-style).

Turns a style number from the handraw-style library into a ready-to-send
bilingual image prompt, following the upstream assembly rules
(``skills/handdraw-style-prompter`` SKILL.md + ``scripts/prompt_style.py``):

* pick a style by canonical id (``FI-001``) or legacy number (``333``);
* optionally combine a layout (``SC-001``) and a theme color (``C-01``);
* the gpt-image-2 activation policy baked into the index decides whether
  the style name alone activates the style, whether the filtered core
  traits are appended, or whether a numbered reference image must
  accompany the prompt;
* ``pure`` mode (upstream ``pure-image``) describes only the theme;
  ``text`` mode (upstream ``graphic-text``) preserves the theme verbatim
  and appends the library's fixed graphic-text suffix.  Selecting a
  layout forces ``text`` mode, except e-commerce layouts (``EC-*``),
  which never take the suffix.

The extracted data lives in ``handraw_data/handraw_index.json`` (rebuild
with ``handraw_data/build_handraw_index.py``); the upstream checkout is
only needed for reference images and lives outside the repo
(``HEVI_HANDRAW_HOME``, default ``~/projects/_refs/handraw-style``).

License: MIT License with Attribution Requirement -- free to use, modify
and commercialize; credit to the original author yang0 and the upstream
repository https://github.com/yang0/handraw-style must be retained.  See
``handraw_data/LICENSE`` and ``handraw_data/ATTRIBUTION.md``.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent / "handraw_data"
_INDEX_PATH = _DATA_DIR / "handraw_index.json"

HANDRAW_SOURCE_URL = "https://github.com/yang0/handraw-style"
ATTRIBUTION = (
    "Style/layout/color data from yang0/handraw-style "
    f"({HANDRAW_SOURCE_URL}); MIT License with Attribution Requirement."
)


class HandrawStyleError(ValueError):
    """Unknown style/layout/color id or bad handraw request."""


def handraw_home() -> Path:
    """Upstream checkout root (reference images only; data is in-repo)."""
    return Path(
        os.environ.get("HEVI_HANDRAW_HOME", "~/projects/_refs/handraw-style")
    ).expanduser()


@lru_cache(maxsize=1)
def load_index() -> dict[str, Any]:
    if not _INDEX_PATH.exists():
        raise HandrawStyleError(
            f"handraw index missing at {_INDEX_PATH}; rebuild it with "
            "hevi/image/handraw_data/build_handraw_index.py"
        )
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


def counts() -> dict[str, int]:
    return dict(load_index()["counts"])


def canonical_style_id(raw: str) -> str:
    """Normalize ``FI-001`` / ``fi1`` / legacy ``333`` to canonical form."""
    index = load_index()
    text = str(raw).strip()
    if text.isdigit():
        num = f"{int(text):03}"
        return index["legacy_to_new"].get(num, num)
    m = re.match(r"^([A-Za-z]{2})[-_]?(\d+)$", text)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2)):03}"
    return text.upper()


def get_style(raw: str) -> dict[str, Any]:
    canonical = canonical_style_id(raw)
    for style in load_index()["styles"]:
        if style["id"] == canonical:
            return style
    # A canonical-looking id may itself be a legacy key (upstream fallback).
    legacy_to_new = load_index()["legacy_to_new"]
    if canonical in legacy_to_new:
        target = legacy_to_new[canonical]
        for style in load_index()["styles"]:
            if style["id"] == target:
                return style
    raise HandrawStyleError(
        f"unknown handraw style id: {raw!r} (use a listed id like FI-001 "
        "or a legacy number 001-365)"
    )


def _normalize_layout_id(raw: str) -> str:
    text = str(raw).strip()
    m = re.match(r"^([A-Za-z]{2,3})[-_]?(\d+)$", text)
    if m:
        return f"{m.group(1).upper()}-{int(m.group(2)):03}"
    return text.upper()


def get_layout(raw: str) -> dict[str, Any]:
    canonical = _normalize_layout_id(raw)
    for layout in load_index()["layouts"]:
        if layout["id"] == canonical:
            return layout
    raise HandrawStyleError(f"unknown handraw layout id: {raw!r}")


def get_color(raw: str) -> dict[str, Any]:
    text = str(raw).strip()
    m = re.match(r"^[Cc][-]?(\d+)$", text)
    canonical = f"C-{int(m.group(1)):02}" if m else None
    for color in load_index()["colors"]:
        if canonical and color["id"] == canonical:
            return color
        if text in (color["name_zh"], color["name_en"]):
            return color
    raise HandrawStyleError(f"unknown handraw color id: {raw!r} (C-01..C-36)")


def search(
    section: str, *, category: str = "", query: str = "", limit: int = 2000
) -> list[dict[str, Any]]:
    """Filter one index section by category prefix and free-text query."""
    items = load_index()[section]
    q = query.strip().lower()
    out: list[dict[str, Any]] = []
    for item in items:
        if category:
            cat = item.get("category", "")
            group = item.get("group", "")
            if not (cat.upper() == category.upper() or group.startswith(category)):
                continue
        if q:
            haystack = json.dumps(item, ensure_ascii=False).lower()
            if q not in haystack:
                continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def reference_image_path(style: dict[str, Any]) -> Path | None:
    """Local numbered reference image for a style, when the checkout has it."""
    rel = style.get("reference_relpath")
    if not rel:
        return None
    path = handraw_home() / rel
    return path if path.exists() else None


def assemble_prompt(
    style_id: str,
    theme: str,
    *,
    layout_id: str | None = None,
    color_id: str | None = None,
    mode: str = "pure",
) -> dict[str, Any]:
    """Assemble bilingual prompts for one styled generation.

    Mirrors upstream ``scripts/prompt_style.py``: style-only requests keep
    bilingual output; a layout selects the theme's language for a single
    combined prompt (we still return both language variants, assembled the
    same way, so callers can choose).  ``mode`` is ``pure`` (upstream
    pure-image) or ``text`` (upstream graphic-text).
    """
    if mode not in ("pure", "text"):
        raise HandrawStyleError(f"mode must be 'pure' or 'text', got {mode!r}")
    theme = str(theme)
    if not theme.strip():
        raise HandrawStyleError("theme must not be empty")
    index = load_index()
    suffix = index["constants"]["graphic_text_suffix"]
    style = get_style(style_id)
    layout = get_layout(layout_id) if layout_id else None
    color = get_color(color_id) if color_id else None
    traits = style["prompt_traits"]
    is_ecommerce = bool(
        layout and (layout["category"] == "ecommerce" or layout["id"].startswith("EC-"))
    )
    effective_mode = mode
    if layout and not is_ecommerce:
        effective_mode = "text"

    if layout:
        zh_parts = [f"图型：{layout['name']}。"]
        en_parts = [f"Layout: {layout['name_en'] or layout['name']}."]
        if color:
            zh_parts.append(color["prompt_zh"])
            en_parts.append(color["prompt_en"])
        zh_parts.append(f"主题：{theme}。")
        en_parts.append(f"Theme: {theme}.")
        zh_parts.append(f"排版要求：{layout['prompt_zh']}")
        en_parts.append(f"Layout instructions: {layout['prompt_en']}")
        zh_parts.append(
            f"风格名称：{style['generation_name']}。参考作者/风格名称：{style['reference']}。"
        )
        en_parts.append(
            f"Style name: {style['generation_name']}. Reference author/style name: {style['reference']}."
        )
        if traits:
            zh_parts.append(f"核心风格特征：{traits}。")
            en_parts.append(f"Core style traits: {traits}.")
        if not is_ecommerce:
            zh_parts.append(suffix)
            en_parts.append(suffix)
        prompt_zh = "".join(zh_parts)
        prompt_en = " ".join(en_parts)
    else:
        color_zh = color["prompt_zh"] if color else ""
        color_en = f" {color['prompt_en']}" if color else ""
        traits_zh = f"核心风格特征：{traits}。" if traits else ""
        traits_en = f" Core style traits: {traits}." if traits else ""
        tail = suffix if effective_mode == "text" else ""
        prompt_zh = (
            f"风格名称：{style['generation_name']}。{color_zh}主题：{theme}。"
            f"参考作者/风格名称：{style['reference']}。{traits_zh}{tail}"
        )
        prompt_en = (
            f"Style name: {style['generation_name']}.{color_en} Theme: {theme}."
            f" Reference author/style name: {style['reference']}.{traits_en}{tail}"
        )

    return {
        "style": style,
        "layout": layout,
        "color": color,
        "mode": effective_mode,
        "activation_source": style["activation"]["source"],
        "prompt_traits": traits,
        "use_reference_image": bool(style["activation"]["use_reference_image"]),
        "prompt_zh": prompt_zh,
        "prompt_en": prompt_en,
    }


def generation_prompt(assembled: dict[str, Any], *, lang: str, reference_attached: bool) -> str:
    """The single prompt actually sent to the image backend.

    When a numbered reference image is attached, the upstream reference
    isolation block is appended (the generation prompt always receives it
    together with the asset, in both modes).
    """
    prompt = assembled["prompt_zh"] if lang == "zh" else assembled["prompt_en"]
    if reference_attached:
        iso = load_index()["constants"][
            "reference_isolation_zh" if lang == "zh" else "reference_isolation_en"
        ]
        prompt = f"{prompt}{iso}" if lang == "zh" else f"{prompt} {iso}"
    return prompt
