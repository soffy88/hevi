#!/usr/bin/env python3
"""Build shotcraft_index.json from the imported shot recipe cards.

Source: Vincentwei1021/video-shotcraft (Apache-2.0), references/shots/.
Each card is a Markdown file with a small frontmatter block:

    ---
    name: basic-3d-scene
    一句话: ...
    适用: ...
    时长: ...
    能量: ...
    标签: ...        (optional)
    ---

followed by sections 意图 / 动效核心 / 参数表 / 已知坑 / 参考实现.
The index keeps the parsed frontmatter plus the demo path taken from
the 参考实现 section; the full card text stays in cards/<category>/.
Re-run after updating the cards from upstream:

    python build_shotcraft_index.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CARDS_DIR = HERE / "cards"
OUT = HERE / "shotcraft_index.json"

SOURCE_URL = "https://github.com/Vincentwei1021/video-shotcraft"
UPSTREAM_COMMIT = "43bd349a136651865ecfa6ea1cf012f6e957d304"

_KEYMAP = {
    "name": "name",
    "一句话": "one_liner",
    "适用": "applies_to",
    "时长": "duration",
    "能量": "energy",
    "标签": "tags",
}

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_DEMO_RE = re.compile(r"demos/[^\s)）\]`]+")


def parse_card(path: Path, category: str) -> dict:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            body = text[end + 4 :]
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                key, sep, value = line.partition(":")
                if not sep:
                    key, sep, value = line.partition("：")
                if not sep:
                    continue
                key = key.strip()
                if key in _KEYMAP:
                    meta[_KEYMAP[key]] = value.strip()
    sections = _SECTION_RE.findall(body)
    demo_match = _DEMO_RE.search(body)
    name = meta.get("name") or path.stem
    return {
        "name": name,
        "category": category,
        "file": f"cards/{category}/{path.name}",
        "one_liner": meta.get("one_liner", ""),
        "applies_to": meta.get("applies_to", ""),
        "duration": meta.get("duration", ""),
        "energy": meta.get("energy", ""),
        "tags": meta.get("tags", ""),
        "demo": demo_match.group(0).rstrip("/") if demo_match else "",
        "sections": sections,
    }


def main() -> None:
    cards: list[dict] = []
    by_category: dict[str, int] = {}
    for cat_dir in sorted(p for p in CARDS_DIR.iterdir() if p.is_dir()):
        for md in sorted(cat_dir.glob("*.md")):
            card = parse_card(md, cat_dir.name)
            cards.append(card)
            by_category[cat_dir.name] = by_category.get(cat_dir.name, 0) + 1
    names = [c["name"] for c in cards]
    assert len(names) == len(set(names)), "duplicate card names"
    payload = {
        "source": SOURCE_URL,
        "license": "Apache-2.0",
        "attribution": (
            "Shot recipe cards from Vincentwei1021/video-shotcraft "
            f"({SOURCE_URL}), Apache License 2.0. See ATTRIBUTION.md "
            "and UPSTREAM_ATTRIBUTION.md in this directory."
        ),
        "upstream_commit": UPSTREAM_COMMIT,
        "counts": {"total": len(cards), "by_category": by_category},
        "cards": cards,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} with {len(cards)} cards: {by_category}")


if __name__ == "__main__":
    main()
