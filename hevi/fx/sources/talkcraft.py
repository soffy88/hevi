"""Parse talkcraft tplMeta.ts to extract FX template entries.

Reads the generated metadata file (read-only) and maps 7 Chinese categories
to 4 registry categories.

Cards whose ``category`` is not in :data:`_CATEGORY_MAP` are **not silently
dropped**: they are logged as a warning and surfaced to the caller (and, via
``hevi.fx.loader.load_all``, on the registry's ``skipped`` map) so a new
talkcraft category can never disappear unnoticed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from hevi.fx.registry import FXTemplate, Category, Source

logger = logging.getLogger(__name__)

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


class TplMetaError(ValueError):
    """Raised when tplMeta.ts is missing or cannot be parsed into entries."""


def _parse_tpl_meta(path: Path) -> list[dict[str, str]]:
    """Parse tplMeta.ts and return list of {id, name_zh, category_zh} dicts.

    Raises:
        FileNotFoundError: the file does not exist.
        TplMetaError: the file exists but no card entries could be parsed
            (wrong format / empty), which would otherwise silently produce an
            empty catalog.
    """
    if not path.exists():
        raise FileNotFoundError(f"tplMeta.ts not found at {path}")

    text = path.read_text(encoding="utf-8")

    # Pattern: "some-id": { name: "中文名", category: "分类名" }
    pattern = re.compile(r'"([^"]+)":\s*\{\s*name:\s*"([^"]+)",\s*category:\s*"([^"]+)"\s*\}')
    entries = []
    for match in pattern.finditer(text):
        card_id, name_zh, category_zh = match.groups()
        entries.append(
            {
                "id": card_id,
                "name_zh": name_zh,
                "category_zh": category_zh,
            }
        )

    if not entries:
        raise TplMetaError(
            f"no card entries parsed from {path} — tplMeta.ts is empty or has an "
            'unexpected format (expected `"id": { name: "…", category: "…" }`)'
        )
    return entries


def load_talkcraft_with_skipped(
    path: Path | None = None,
) -> tuple[list[FXTemplate], list[dict[str, str]]]:
    """Load talkcraft templates and report any entries that were skipped.

    Args:
        path: Override for the tplMeta.ts location (defaults to the repo file).
            Used by tests to feed synthetic metadata.

    Returns:
        ``(templates, skipped)`` where ``skipped`` lists ``{id, name_zh,
        category_zh, reason}`` for cards whose category is not mapped.

    Raises:
        FileNotFoundError: tplMeta.ts missing.
        TplMetaError: tplMeta.ts present but unparseable.
    """
    src = path or _TPL_META_PATH
    entries = _parse_tpl_meta(src)
    templates: list[FXTemplate] = []
    skipped: list[dict[str, str]] = []

    for entry in entries:
        card_id = entry["id"]
        name_zh = entry["name_zh"]
        category_zh = entry["category_zh"]

        category = _CATEGORY_MAP.get(category_zh)
        if category is None:
            skipped.append(
                {
                    "id": card_id,
                    "name_zh": name_zh,
                    "category_zh": category_zh,
                    "reason": f"unmapped category '{category_zh}' (not in _CATEGORY_MAP)",
                }
            )
            logger.warning(
                "talkcraft: skipping card '%s' (%s) — category '%s' is not in "
                "_CATEGORY_MAP; add it to hevi/fx/sources/talkcraft.py to include it",
                card_id,
                name_zh,
                category_zh,
            )
            continue

        templates.append(
            FXTemplate(
                id=f"tc:{card_id}",
                name_zh=name_zh,
                category=category,
                source=Source.TALKCRAFT,
                source_ref=card_id,
                tags=[card_id, category_zh, "talkcraft"],
                duration_hint=None,  # real card duration is read at render time
            )
        )

    return templates, skipped


def load_talkcraft(path: Path | None = None) -> list[FXTemplate]:
    """Load all talkcraft templates from tplMeta.ts.

    Unmapped categories are logged as warnings (see
    :func:`load_talkcraft_with_skipped` for the machine-readable list).
    """
    templates, _skipped = load_talkcraft_with_skipped(path)
    return templates
