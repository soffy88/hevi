#!/usr/bin/env python3
"""Build hevi's handraw-style index from the upstream checkout.

Source: yang0/handraw-style (MIT License with Attribution Requirement --
see ``LICENSE`` in this directory and ``ATTRIBUTION.md``). The upstream
skill's own ``references/*.json`` files are the authoritative data; this
script extracts the subset hevi needs into one self-contained JSON index
(``handraw_index.json`` next to this script) so the runtime never parses
the upstream tree:

* styles (365): canonical id, legacy 001-365 number, group, reference
  (author/style label), generation name, raw traits, the gpt-image-2
  prompt traits (upstream ``positive_traits`` filter) and the activation
  decision mirrored from upstream ``scripts/resolve_reference.py`` for
  model ``gpt-image-2``.
* layouts (167): id, category, names, keywords, and the bilingual layout
  prompts parsed out of ``references/layouts/<ID>.md``.
* colors (36) and tones (16): ids, names, prompt snippets.

Usage:
    HEVI_HANDRAW_HOME=~/projects/_refs/handraw-style \
        python3 build_handraw_index.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

UPSTREAM_URL = "https://github.com/yang0/handraw-style"
MODEL = "gpt-image-2"

# Verbatim constants from upstream skills/handdraw-style-prompter
# (SKILL.md "Prompt modes" and scripts/prompt_style.py).
GRAPHIC_TEXT_SUFFIX = "【如果主题直白包含画面元素那就按主题出图，文案由你来升华，但是不要直接描述画面。 如果主题比较概念化，那么文案和主题尽量保持一致，如果文案较长由你提炼，由你先设计画面隐喻（人类和非人类都行）再出图   。    文字参与构图，图文一体】"
REFERENCE_ISOLATION_ZH = (
    "所附图片仅用于参考画风。只提取参考图的风格特征，例如线条、笔触、媒介、材质、色彩倾向和整体视觉语言；"
    "不要使用、复制或延续参考图中的任何主体、人物、动物、服装、道具、动作、姿态、场景、背景、构图、布局、文字或故事。"
    "最终画面内容完全以用户提供的主题为准。"
)
REFERENCE_ISOLATION_EN = (
    "Use the attached image only as a style reference. Extract only its stylistic qualities, such as linework, brushwork, medium, "
    "material texture, color tendencies, and overall visual language. Do not use, copy, or carry over any subject, person, animal, "
    "clothing, prop, action, pose, setting, background, composition, layout, text, or story from the reference image. "
    "The user's written theme is the sole source for the image content."
)

_KEEP_RAW_IDS = {"FE-048", "FE-049", "FE-051", "FH-050", "FD-042"}
_KEEP_RAW_LEGACY = {"240", "242", "257", "259", "260"}


def positive_traits(traits: str) -> str:
    """Mirror of upstream ``resolve_reference.positive_traits``."""
    if not traits:
        return ""
    kept: list[str] = []
    for part in re.split(r"[；;。\n]+", traits):
        part = part.strip(" ，,、：:。；;\t")
        if not part:
            continue
        if any(word in part for word in ("避免", "不要", "不准", "禁止")):
            continue
        if re.search(r"无(?:写实纹理|精细材质|真实纹理)", part):
            continue
        kept.append(part)
    return "；".join(kept)


def resolve_activation(policy: dict, number: str, legacy_number: str, raw_traits: str) -> dict:
    """Mirror of upstream ``resolve_reference.resolve`` for MODEL."""
    fallback = dict(policy["default"])
    profile = policy.get("models", {}).get(MODEL) or {}
    entry = dict(fallback)
    entry.update({k: v for k, v in profile.items() if k != "styles"})
    style_entry = profile.get("styles", {}).get(number) or profile.get("styles", {}).get(legacy_number, {})
    entry.update(style_entry)
    name_activation = entry.get("name_activation", "unknown")
    traits_activation = entry.get("traits_activation", "unknown")
    keep_raw = number in _KEEP_RAW_IDS or legacy_number in _KEEP_RAW_LEGACY
    traits = raw_traits if keep_raw else positive_traits(raw_traits)
    if name_activation == "strong":
        activation_source, use_ref, prompt_traits = "name+style", False, ""
    elif traits_activation == "strong" and traits:
        activation_source, use_ref, prompt_traits = "name+style+traits", False, traits
    else:
        use_ref = True
        prompt_traits = traits
        activation_source = "name+style+traits+reference-image" if prompt_traits else "name+style+reference-image"
    return {
        "name_activation": name_activation,
        "traits_activation": traits_activation,
        "activation_source": activation_source,
        "use_reference_image": use_ref,
        "prompt_traits": prompt_traits,
    }


def _load(refs: Path, name: str):
    return json.loads((refs / name).read_text(encoding="utf-8"))


def _layout_prompts(refs: Path, layout_id: str) -> dict[str, str]:
    text = (refs / "layouts" / f"{layout_id}.md").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"<!--\s*(zh|en)\s*-->", line.strip())
        if m:
            if current:
                out[current] = "\n".join(buf).strip()
            current, buf = m.group(1), []
        elif current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


def main() -> None:
    home = Path(os.environ.get("HEVI_HANDRAW_HOME", "~/projects/_refs/handraw-style")).expanduser()
    refs = home / "skills" / "handdraw-style-prompter" / "references"
    if not refs.is_dir():
        raise SystemExit(f"upstream references not found under {home}")

    styles_raw = _load(refs, "styles.json")
    alias = _load(refs, "style_alias_map.json")
    legacy_to_new = alias.get("legacy_to_new", {})
    new_to_legacy = alias.get("new_to_legacy", {})
    policy = _load(refs, "model_capabilities.json")

    styles = []
    for s in styles_raw:
        number = s["number"]
        legacy = new_to_legacy.get(number, "")
        act = resolve_activation(policy, number, legacy, s.get("traits", ""))
        category = number.split("-")[0]
        grid = home / "images" / "individual" / category / f"{number}_grid.webp"
        single = home / "images" / "individual" / category / f"{number}.webp"
        rel = None
        for cand in (grid, single):
            if cand.exists():
                rel = str(cand.relative_to(home))
                break
        styles.append(
            {
                "id": number,
                "legacy_number": legacy,
                "category": category,
                "group": s.get("group", ""),
                "reference": s.get("reference", ""),
                "generation_name": s.get("generation_name", ""),
                "traits": s.get("traits", ""),
                "prompt_traits": act["prompt_traits"],
                "activation": {
                    "source": act["activation_source"],
                    "name_activation": act["name_activation"],
                    "traits_activation": act["traits_activation"],
                    "use_reference_image": act["use_reference_image"],
                },
                "reference_relpath": rel,
            }
        )

    layouts = []
    for lay in _load(refs, "layouts.json"):
        prompts = _layout_prompts(refs, lay["id"])
        layouts.append(
            {
                "id": lay["id"],
                "category": lay.get("category", ""),
                "name": lay.get("name", ""),
                "name_en": lay.get("name_en", ""),
                "keywords": lay.get("keywords", []),
                "prompt_zh": prompts.get("zh", ""),
                "prompt_en": prompts.get("en", ""),
            }
        )

    colors = [
        {
            "id": c["id"],
            "category": c.get("category", ""),
            "category_zh": c.get("category_zh", ""),
            "category_en": c.get("category_en", ""),
            "name_zh": c.get("name_zh", ""),
            "name_en": c.get("name_en", ""),
            "prompt_zh": c.get("prompt_zh", ""),
            "prompt_en": c.get("prompt_en", ""),
        }
        for c in _load(refs, "colors.json")
    ]
    tones = [
        {
            "id": t["id"],
            "category": t.get("category", ""),
            "name_zh": t.get("name_zh", ""),
            "name_en": t.get("name_en", ""),
            "desc_zh": t.get("desc_zh", ""),
            "desc_en": t.get("desc_en", ""),
        }
        for t in _load(refs, "tones.json")
    ]

    version_file = home / "version.json"
    upstream_version = ""
    if version_file.exists():
        upstream_version = json.loads(version_file.read_text(encoding="utf-8")).get("version", "")

    index = {
        "source": UPSTREAM_URL,
        "license": (
            "MIT License with Attribution Requirement -- free to use, modify "
            "and commercialize; credit to author yang0 and the upstream "
            "repository must be retained (see LICENSE + ATTRIBUTION.md in "
            "this directory)."
        ),
        "attribution": f"Style/layout/color data from yang0/handraw-style ({UPSTREAM_URL}), version {upstream_version}.",
        "upstream_version": upstream_version,
        "model_profile": MODEL,
        "constants": {
            "graphic_text_suffix": GRAPHIC_TEXT_SUFFIX,
            "reference_isolation_zh": REFERENCE_ISOLATION_ZH,
            "reference_isolation_en": REFERENCE_ISOLATION_EN,
        },
        "legacy_to_new": legacy_to_new,
        "counts": {"styles": len(styles), "layouts": len(layouts), "colors": len(colors), "tones": len(tones)},
        "styles": styles,
        "layouts": layouts,
        "colors": colors,
        "tones": tones,
    }
    out = Path(__file__).resolve().parent / "handraw_index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}: {index['counts']}")


if __name__ == "__main__":
    main()
