"""Idea2Video 文本原子:预算、slug、分场、人名启发式。

3O 归属(待上游): `oprim.idea_parse`。
"""

from __future__ import annotations

import re
from pathlib import PurePath

from hevi.script2video.adapter_schemas import LengthBudget

_SCENE_SPLIT = re.compile(
    r"(?:^|\n)\s*(?:场(?:次|景)?\s*[一二三四五六七八九十\d]+|"
    r"Scene\s+\d+|INT\.|EXT\.)",
    re.IGNORECASE,
)
_NAME_PATTERNS = (
    re.compile(r"「([^」]{1,12})」"),
    re.compile(r"“([^”]{1,12})”"),
    re.compile(r"<([^>]{1,24})>"),
    re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
)
_SCENE_COUNT = re.compile(r"(?:不超过|最多|不超过|no more than)\s*(\d+)\s*(?:场|scenes?)", re.I)
_SHOT_COUNT = re.compile(r"(?:不超过|最多|不超过|no more than)\s*(\d+)\s*(?:镜|shots?)", re.I)
_DEFAULT_BUDGET = LengthBudget(max_scenes=1, max_shots_per_scene=5)


def parse_length_budget(requirement: str, *, default: LengthBudget | None = None) -> LengthBudget:
    """ViMax Agent 默认 1 场 3-5 镜;用户写明场/镜数才放大。"""
    budget = default or LengthBudget(
        max_scenes=_DEFAULT_BUDGET.max_scenes,
        max_shots_per_scene=_DEFAULT_BUDGET.max_shots_per_scene,
    )
    scene_hit = _SCENE_COUNT.search(requirement or "")
    shot_hit = _SHOT_COUNT.search(requirement or "")
    if scene_hit:
        budget.max_scenes = max(1, int(scene_hit.group(1)))
    if shot_hit:
        budget.max_shots_per_scene = max(1, int(shot_hit.group(1)))
    return budget


def slugify(name: str) -> str:
    text = (name or "").strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text, flags=re.UNICODE)
    return text.strip("_") or "character"


def photo_stem_name(path: str) -> str:
    return PurePath(path).stem.replace("_", " ").replace("-", " ").strip() or "Cameo"


def split_story_scenes(story: str, *, max_scenes: int) -> list[str]:
    """按场标题切;没有标题则按空行均分,再封顶。"""
    text = (story or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in _SCENE_SPLIT.split(text) if part.strip()]
    if len(parts) <= 1:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        parts = paras if paras else [text]
    if len(parts) > max_scenes:
        head, tail = parts[: max_scenes - 1], parts[max_scenes - 1 :]
        parts = [*head, "\n\n".join(tail)]
    return parts[:max_scenes]


def extract_name_candidates(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    stop = {"The", "A", "An", "INT", "EXT", "Day", "Night", "Scene"}
    for pattern in _NAME_PATTERNS:
        for match in pattern.findall(text or ""):
            name = match.strip()
            if name in stop or len(name) < 2:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(name)
    return found
