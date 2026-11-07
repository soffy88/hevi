"""Opus 5.5 code-video prompt library (``story.opus_prompt_library``).

Method intake from the 2026-10-28 five-repo collection, search layer
only -- no new generation here:

* yihui-dev/awesome-opus5-5-videos (MIT): the bundled index keeps the
  full prompt text, category, tech tags, author and original-post link
  for all 703 entries, with ``prompt_partial`` preserved (207 entries
  are partial prompts, not complete ones -- a caller must not present
  a partial prompt as a complete recipe).
* zhuyansen/awesome-opus-5.5-video (no LICENSE on record): the bundled
  index keeps metadata ONLY -- id, models, category, Chinese/English
  title, creator handle, original-post URL, duration and views. No
  prompt text, no prompt link and no thumbnail is bundled from this
  repo, so nothing unlicensed is redistributed; use the original-post
  URL to read the creator's own post.

Search is deterministic and local: filter by category and/or tech tag,
substring-match on author/slug/title, sort by the requested key, and
cap the result list. An unknown category or tech tag is an error, not
a silent empty result, so a typo cannot be mistaken for "no match".

Failure contract: unknown source, unknown category/tech tag, a
non-positive limit, or a missing bundled index file all raise
CapabilityError. The zhuyansen index never returns prompt text:
``get_prompt`` for a zhuyansen id raises with the original-post URL
instead of inventing one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False
_DATA = Path(__file__).resolve().parent / "opus_prompt_data"

_YIHUI_CATEGORIES = {"motion", "3d", "explainer", "interactive"}
_ZHUYANSEN_CATEGORIES = {
    "comparison", "game", "art3d", "motion",
    "product", "stories", "education", "production",
}
# Category wording the caller uses -> yihui's own category names.
_CATEGORY_ALIASES = {
    "动效": "motion", "解说": "explainer", "3d": "3d", "三维": "3d",
    "游戏": "interactive", "互动": "interactive", "mv": "motion",
    "music": "motion", "音乐": "motion",
}


def _load(name: str) -> dict[str, Any]:
    path = _DATA / name
    if not path.exists():
        raise CapabilityError(
            f"story.opus_prompt_library: bundled index missing: {path.name}"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise CapabilityError(
            f"story.opus_prompt_library: bundled index unreadable: {exc}"
        ) from exc


def _norm_category(source: str, category: str | None) -> str | None:
    if category is None:
        return None
    cat = _CATEGORY_ALIASES.get(category.strip(), category.strip())
    allowed = _YIHUI_CATEGORIES if source == "yihui" else _ZHUYANSEN_CATEGORIES
    if cat not in allowed:
        raise CapabilityError(
            f"story.opus_prompt_library: unknown {source} category {category!r}; "
            f"known: {sorted(allowed)}"
        )
    return cat


def _norm_tech(tech: str | None) -> str | None:
    if tech is None:
        return None
    return tech.strip().lower().replace(".js", "js")


def list_categories(source: str = "yihui") -> list[str]:
    if source == "yihui":
        return sorted(_YIHUI_CATEGORIES)
    if source == "zhuyansen":
        return sorted(_ZHUYANSEN_CATEGORIES)
    raise CapabilityError(
        "story.opus_prompt_library: source must be 'yihui' or 'zhuyansen'"
    )


def list_tech_tags() -> list[str]:
    data = _load("yihui_index.json")
    tags: set[str] = set()
    for entry in data["entries"]:
        tags.update(t.lower() for t in entry.get("tech_tags") or [])
    return sorted(tags)


def search_prompts(
    source: str = "yihui",
    category: str | None = None,
    tech: str | None = None,
    query: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    if source not in ("yihui", "zhuyansen"):
        raise CapabilityError(
            "story.opus_prompt_library: source must be 'yihui' or 'zhuyansen'"
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise CapabilityError("story.opus_prompt_library: limit must be a positive integer")
    cat = _norm_category(source, category)
    tag = _norm_tech(tech)
    if source == "yihui" and tag is not None:
        known = set(list_tech_tags())
        if tag not in known:
            raise CapabilityError(
                f"story.opus_prompt_library: unknown tech tag {tech!r}; known: {sorted(known)}"
            )
    data = _load("yihui_index.json" if source == "yihui" else "zhuyansen_meta.json")
    q = (query or "").strip().lower()
    hits: list[dict[str, Any]] = []
    for entry in data["entries"]:
        if cat is not None and entry.get("category") != cat:
            continue
        if tag is not None and tag not in [t.lower() for t in entry.get("tech_tags") or []]:
            continue
        if q:
            hay = " ".join(str(entry.get(k) or "") for k in
                           ("slug", "author", "category", "title_en", "title_zh")).lower()
            if q not in hay:
                continue
        if source == "yihui":
            hits.append({
                "slug": entry["slug"], "category": entry["category"],
                "tech_tags": entry.get("tech_tags") or [],
                "author": entry.get("author"), "post_url": entry.get("post_url"),
                "prompt_partial": entry.get("prompt_partial", False),
                "prompt_chars": len(entry.get("prompt") or ""),
            })
        else:
            hits.append({
                "id": entry["id"], "category": entry["category"],
                "models": entry.get("models") or [],
                "title_en": entry.get("title_en"), "title_zh": entry.get("title_zh"),
                "creator": entry.get("creator"),
                "original_post_url": entry.get("original_post_url"),
                "duration_seconds": entry.get("duration_seconds"),
                "views": entry.get("views"),
                "prompt_text": None,
                "prompt_note": "zhuyansen index is metadata only; read the original post",
            })
    return {
        "capability": "story.opus_prompt_library", "source": source,
        "total_in_index": data["count"], "matched": len(hits),
        "category": cat, "tech": tag, "query": query,
        "results": hits[:limit],
    }


def get_prompt(slug: str) -> dict[str, Any]:
    if not isinstance(slug, str) or not slug.strip():
        raise CapabilityError("story.opus_prompt_library: slug must be a non-empty string")
    slug = slug.strip()
    data = _load("yihui_index.json")
    for entry in data["entries"]:
        if entry["slug"] == slug:
            return {
                "capability": "story.opus_prompt_library", "source": "yihui",
                "slug": slug, "category": entry["category"],
                "tech_tags": entry.get("tech_tags") or [],
                "author": entry.get("author"), "post_url": entry.get("post_url"),
                "prompt": entry.get("prompt") or "",
                "prompt_partial": entry.get("prompt_partial", False),
                "license": "MIT (yihui-dev/awesome-opus5-5-videos)",
            }
    meta = _load("zhuyansen_meta.json")
    for entry in meta["entries"]:
        if entry["id"] == slug:
            raise CapabilityError(
                "story.opus_prompt_library: zhuyansen entry has no bundled prompt text; "
                f"read the creator's original post: {entry.get('original_post_url')}"
            )
    raise CapabilityError(f"story.opus_prompt_library: unknown slug/id {slug!r}")


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = params.get("action", "search")
    if action == "search":
        result = search_prompts(
            source=params.get("source", "yihui"),
            category=params.get("category"),
            tech=params.get("tech"),
            query=params.get("query"),
            limit=params.get("limit", 20),
        )
    elif action == "get":
        result = get_prompt(params["slug"])
    elif action == "categories":
        result = {"capability": "story.opus_prompt_library",
                  "yihui": sorted(_YIHUI_CATEGORIES),
                  "zhuyansen": sorted(_ZHUYANSEN_CATEGORIES),
                  "tech_tags": list_tech_tags()}
    else:
        raise CapabilityError(
            "story.opus_prompt_library: action must be 'search', 'get' or 'categories'"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "opus_prompt_library.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "matched": result.get("matched")},
    )


def register_opus_prompt_library_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="story.opus_prompt_library",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "source": {"type": "string"},
                "category": {"type": "string"},
                "tech": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "slug": {"type": "string"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Opus 5.5 code-video prompt library (clean-room search layer): "
            "search yihui 703 full prompts by category/tech tag, or zhuyansen "
            "2220 works by metadata only (no prompt text bundled, no "
            "unlicensed redistribution). Report only; never generates video."
        ),
        line="story",
    ))
    return ["story.opus_prompt_library"]


register_opus_prompt_library_capabilities_once()
