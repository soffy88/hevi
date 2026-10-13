"""Parse talkcraft tplMeta.ts to extract FX template entries.

Reads the generated metadata file (read-only) and maps 7 Chinese categories
to 4 registry categories.
"""

from __future__ import annotations

import re
from pathlib import Path

from hevi.fx.registry import FXTemplate, Category, Source

# Path to the tplMeta.ts file (relative to repo root)
_TPL_META_PATH = (
    Path(__file__).resolve().parents[3] / "hevi-remotion-talkcraft" / "src" / "cards" / "tplMeta.ts"
)

# Mapping from Chinese category names to registry Category enum
_CATEGORY_MAP: dict[str, Category] = {
    "转场结构": Category.TRANSITION,
    "人物互动": Category.CHARACTER,
    "运镜": Category.STYLE,
    "字幕花字": Category.STYLE,
    "素材呈现": Category.STYLE,
    "强调标注": Category.OVERLAY,
    "数据信息图": Category.OVERLAY,
}


def _parse_tpl_meta(path: Path) -> list[dict[str, str]]:
    """Parse tplMeta.ts and return list of {id, name_zh, category_zh} dicts."""
    text = path.read_text(encoding="utf-8")

    # Pattern: "some-id": { name: "中文名", category: "分类名" }
    pattern = re.compile(
        r'"([^"]+)":\s*\{\s*name:\s*"([^"]+)",\s*category:\s*"([^"]+)"\s*\}'
    )
    entries = []
    for match in pattern.finditer(text):
        card_id, name_zh, category_zh = match.groups()
        entries.append({
            "id": card_id,
            "name_zh": name_zh,
            "category_zh": category_zh,
        })
    return entries


def load_talkcraft() -> list[FXTemplate]:
    """Load all talkcraft templates from tplMeta.ts.

    Returns:
        List of FXTemplate entries for all talkcraft cards.
    """
    if not _TPL_META_PATH.exists():
        raise FileNotFoundError(f"tplMeta.ts not found at {_TPL_META_PATH}")

    entries = _parse_tpl_meta(_TPL_META_PATH)
    templates = []

    for entry in entries:
        card_id = entry["id"]
        name_zh = entry["name_zh"]
        category_zh = entry["category_zh"]

        category = _CATEGORY_MAP.get(category_zh)
        if category is None:
            # Unknown category — skip with warning (shouldn't happen)
            continue

        # Generate a unique ID: source_cardid
        template_id = f"tc:{card_id}"

        # Derive tags from the card id and category
        tags = [card_id, category_zh, "talkcraft"]

        templates.append(FXTemplate(
            id=template_id,
            name_zh=name_zh,
            category=category,
            source=Source.TALKCRAFT,
            source_ref=card_id,
            tags=tags,
            duration_hint=None,  # Let the actual card duration be read at render time
        ))

    return templates