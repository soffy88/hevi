#!/usr/bin/env python3
"""Build hevi's handraw-style index from the upstream checkout.

Source: yang0/handraw-style (MIT License with Attribution Requirement --
see ``LICENSE`` in this directory and ``ATTRIBUTION.md``). The upstream
skill's own ``references/*.json`` files are the authoritative data; this
script extracts the subset hevi needs into one self-contained JSON index
(``handraw_index.json`` next to this script) so the runtime never parses
the upstream tree:

* styles: canonical id, legacy number, group, use cases, generation name,
  raw traits, prompt traits, activation decision, and a *sanitized* style
  label.  References whose upstream label is a living (or unconfirmed)
  artist's real name are stripped from hevi; only the style traits remain.
  The policy is stored as SHA-256 hashes in ``credit_policy.json`` so the
  checkout never carries the names.
* layouts: id, category, names, keywords, use cases, and the bilingual
  layout prompts parsed out of ``references/layouts/<ID>.md``.
* colors: ids, names, prompt snippets and a display hex used for colour
  locking (approximate, for UI/covers; prompts stay upstream-verbatim).
* tones: ids, names, descriptions.

Usage:
    HEVI_HANDRAW_HOME=~/projects/_refs/handraw-style \
        python3 build_handraw_index.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

UPSTREAM_URL = "https://github.com/yang0/handraw-style"
MODEL = "gpt-image-2"

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

STYLE_USE_CASES: dict[str, list[str]] = {
    "FA": ["社论", "观点", "幽默", "日常"],
    "FB": ["儿童", "绘本", "温情", "叙事"],
    "FC": ["品牌", "海报", "现代", "商业"],
    "FD": ["情感", "生活方式", "治愈"],
    "FE": ["国风", "历史", "文化", "节庆"],
    "FF": ["儿童", "产品", "手工", "立体"],
    "FG": ["动画", "短剧", "二次元"],
    "FH": ["实验", "艺术", "先锋", "封面"],
    "FI": ["摄影", "写实", "时尚", "产品", "大片"],
}

LAYOUT_USE_CASES: dict[str, list[str]] = {
    "social-card": ["小红书", "朋友圈", "社媒卡", "封面"],
    "social-cards": ["小红书", "朋友圈", "社媒卡", "封面"],
    "infographic": ["知识讲解", "信息图", "长图", "图解"],
    "infographics": ["知识讲解", "信息图", "长图", "图解"],
    "comic-storyboard": ["漫画分镜", "漫剧", "关键帧", "分镜"],
    "ip-character": ["IP", "角色", "形象"],
    "ip-characters": ["IP", "角色", "形象"],
    "ecommerce": ["电商", "产品", "带货"],
}

COLOR_HEX: dict[str, str] = {
    "C-01": "#002FA7", "C-02": "#6050DC", "C-03": "#003153", "C-04": "#0047AB",
    "C-05": "#3F00FF", "C-06": "#005F69", "C-07": "#0ABAB5", "C-08": "#007BA7",
    "C-09": "#98FF98", "C-10": "#9CAF88", "C-11": "#50C878", "C-12": "#708238",
    "C-13": "#3B7A57", "C-14": "#228B22", "C-15": "#E34234", "C-16": "#C8102E",
    "C-17": "#800020", "C-18": "#B03A2E", "C-19": "#C21E56", "C-20": "#FF00FF",
    "C-21": "#F88379", "C-22": "#BC8F8F", "C-23": "#B57EDC", "C-24": "#6B3FA0",
    "C-25": "#F37021", "C-26": "#EC5800", "C-27": "#FADA5E", "C-28": "#E1AD01",
    "C-29": "#CC7722", "C-30": "#FFFFF0", "C-31": "#536878", "C-32": "#36454F",
    "C-33": "#B0A8A0", "C-34": "#FFFDD0", "C-35": "#708090", "C-36": "#A89F91",
}


def positive_traits(traits: str) -> str:
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


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    home = Path(os.environ.get("HEVI_HANDRAW_HOME", "~/projects/_refs/handraw-style")).expanduser()
    refs = home / "skills" / "handdraw-style-prompter" / "references"
    if not refs.is_dir():
        raise SystemExit(f"upstream references not found under {home}")

    policy_path = Path(__file__).resolve().parent / "credit_policy.json"
    credit = json.loads(policy_path.read_text(encoding="utf-8"))
    scrub_path = Path(__file__).resolve().parent / "credit_scrub.json"
    scrub = json.loads(scrub_path.read_text(encoding="utf-8")) if scrub_path.exists() else {}
    removed_hashes = set(credit.get("hashes") or [])
    replacements = dict(credit.get("replacements") or {})
    status_map = dict(credit.get("status_sha256") or {})

    styles_raw = _load(refs, "styles.json")
    alias = _load(refs, "style_alias_map.json")
    legacy_to_new = alias.get("legacy_to_new", {})
    new_to_legacy = alias.get("new_to_legacy", {})
    capabilities = _load(refs, "model_capabilities.json")

    styles = []
    removed_count = 0
    for s in styles_raw:
        number = s["number"]
        legacy = new_to_legacy.get(number, "")
        reference = str(s.get("reference", ""))
        ref_hash = _sha(reference)
        credit_removed = ref_hash in removed_hashes
        if credit_removed:
            removed_count += 1
            style_label = replacements.get(ref_hash, "")
        else:
            style_label = reference
        cleaned = scrub.get(number) or {}
        generation_name = cleaned.get("generation_name") or s.get("generation_name", "")
        traits = cleaned.get("traits") or s.get("traits", "")
        act = resolve_activation(capabilities, number, legacy, traits)
        category = number.split("-")[0]
        styles.append(
            {
                "id": number,
                "legacy_number": legacy,
                "category": category,
                "group": s.get("group", ""),
                "generation_name": generation_name,
                "reference": style_label,
                "credit_removed": credit_removed,
                "credit_status": status_map.get(ref_hash, "descriptive"),
                "use_cases": STYLE_USE_CASES.get(category, []),
                "traits": traits,
                "prompt_traits": act["prompt_traits"],
                "activation": {
                    "source": act["activation_source"],
                    "name_activation": act["name_activation"],
                    "traits_activation": act["traits_activation"],
                    "use_reference_image": act["use_reference_image"],
                },
                "reference_relpath": None,
            }
        )

    layouts = []
    for lay in _load(refs, "layouts.json"):
        prompts = _layout_prompts(refs, lay["id"])
        category = lay.get("category", "")
        layouts.append(
            {
                "id": lay["id"],
                "category": category,
                "name": lay.get("name", ""),
                "name_en": lay.get("name_en", ""),
                "keywords": lay.get("keywords", []),
                "use_cases": LAYOUT_USE_CASES.get(category, []),
                "prompt_zh": prompts.get("zh", ""),
                "prompt_en": prompts.get("en", ""),
            }
        )

    colors = []
    for c in _load(refs, "colors.json"):
        colors.append(
            {
                "id": c["id"],
                "category": c.get("category", ""),
                "category_zh": c.get("category_zh", ""),
                "category_en": c.get("category_en", ""),
                "name_zh": c.get("name_zh", ""),
                "name_en": c.get("name_en", ""),
                "quote_zh": c.get("quote_zh", ""),
                "hex": COLOR_HEX.get(c["id"], ""),
                "prompt_zh": c.get("prompt_zh", ""),
                "prompt_en": c.get("prompt_en", ""),
            }
        )
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

    groups: dict[str, dict] = {}
    for style in styles:
        g = groups.setdefault(
            style["category"],
            {"category": style["category"], "group": style["group"], "count": 0, "use_cases": style["use_cases"]},
        )
        g["count"] += 1

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
        "credit_policy": {
            "removed_entries": removed_count,
            "rule": "Living or unconfirmed contemporary artist names are removed; only style traits are kept.",
            "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        },
        "constants": {
            "graphic_text_suffix": GRAPHIC_TEXT_SUFFIX,
            "reference_isolation_zh": REFERENCE_ISOLATION_ZH,
            "reference_isolation_en": REFERENCE_ISOLATION_EN,
        },
        "legacy_to_new": legacy_to_new,
        "groups": [groups[k] for k in sorted(groups)],
        "counts": {
            "styles": len(styles),
            "layouts": len(layouts),
            "colors": len(colors),
            "tones": len(tones),
            "styles_removed_credit": removed_count,
        },
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
