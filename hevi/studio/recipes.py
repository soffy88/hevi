"""产线配方 —— YAML 声明槽位/工具/阶段,执行走已有 pipeline manifest。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from hevi.pipeline.manifest import PipelineManifest

LINES_DIR = Path(__file__).resolve().parent / "lines"


class SlotSpec(BaseModel):
    name: str
    required: bool = False
    description: str = ""


class Recipe(BaseModel):
    """一条产线:产品名 + 交接目标 + 槽位 + 工具箱 + 可执行阶段。"""

    id: str
    product: str
    summary: str
    handoff: str = "none"  # tongjian | shortdrama | explainer | none
    slots: list[SlotSpec] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    render_runtime: str = "remotion"  # remotion | hyperframes | ffmpeg — proposal 期锁定
    pipeline: PipelineManifest

    @field_validator("handoff")
    @classmethod
    def _known_handoff(cls, v: str) -> str:
        allowed = {"tongjian", "shortdrama", "explainer", "none"}
        if v not in allowed:
            raise ValueError(f"handoff must be one of {sorted(allowed)}")
        return v

    def missing_slots(self, filled: dict[str, Any]) -> list[str]:
        return [s.name for s in self.slots if s.required and not filled.get(s.name)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "product": self.product,
            "summary": self.summary,
            "handoff": self.handoff,
            "slots": [s.model_dump() for s in self.slots],
            "tools": list(self.tools),
            "render_runtime": self.render_runtime,
            "stages": [st.name for st in self.pipeline.stages],
        }


def parse_recipe(text: str) -> Recipe:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("recipe must be a mapping")
    return Recipe.model_validate(data)


def load_recipe(path: Path) -> Recipe:
    return parse_recipe(path.read_text(encoding="utf-8"))


def load_recipes(directory: Path | None = None) -> dict[str, Recipe]:
    root = directory or LINES_DIR
    recipes: dict[str, Recipe] = {}
    if not root.exists():
        return recipes
    for path in sorted(root.glob("*.yaml")):
        rec = load_recipe(path)
        recipes[rec.id] = rec
    return recipes


_CACHE: dict[str, Recipe] | None = None


def list_recipes(*, refresh: bool = False) -> list[Recipe]:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = load_recipes()
    return list(_CACHE.values())


def get_recipe(line_id: str, *, refresh: bool = False) -> Recipe | None:
    global _CACHE
    if _CACHE is None or refresh:
        _CACHE = load_recipes()
    return _CACHE.get(line_id)
