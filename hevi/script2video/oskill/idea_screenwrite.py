"""点子 → 故事 → 角色 → 分场剧本。

组合: `parse_length_budget` + `split_story_scenes` + `extract_name_candidates` + `slugify`。
3O 归属(待上游): `oskill.idea_screenwrite`。
LLM 可注入;缺省走可拍脚手架,不阻断。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from hevi.script2video.adapter_schemas import IdeaStory, LengthBudget, SceneScript
from hevi.script2video.oprim.idea_parse import (
    extract_name_candidates,
    parse_length_budget,
    slugify,
    split_story_scenes,
)
from hevi.script2video.schemas import KernelCharacter

LLMFn = Callable[..., Awaitable[Any] | Any]


def develop_story(
    idea: str,
    requirement: str = "",
    *,
    budget: LengthBudget | None = None,
) -> IdeaStory:
    """无 LLM 脚手架:三幕骨架 + 按场标题,语言跟输入走。"""
    budget = budget or parse_length_budget(requirement)
    audience = _pick_tagged(requirement, ("小孩", "儿童", "adult", "成人"), default="all ages")
    genre = _pick_tagged(requirement, ("卡通", "cartoon", "写实", "realistic"), default="cinematic")
    title = idea.strip().splitlines()[0][:40] if idea.strip() else "Untitled"
    scenes = [
        (
            f"Scene {idx + 1}: {idea.strip()} — beat {idx + 1}/{budget.max_scenes}. "
            "Show actions, facing, and environment; do not only narrate emotion."
        )
        for idx in range(budget.max_scenes)
    ]
    body = "\n\n".join(scenes)
    outline = (
        f"A {budget.max_scenes}-scene story from the idea. "
        f"Each scene stays under {budget.max_shots_per_scene} shots."
    )
    return IdeaStory(
        title=title,
        audience=audience,
        genre=genre,
        outline=outline,
        body=body,
        scene_headings=[f"Scene {i + 1}" for i in range(budget.max_scenes)],
    )


def extract_characters(story: str, idea: str = "") -> list[KernelCharacter]:
    names = extract_name_candidates(f"{idea}\n{story}")
    if not names:
        names = [idea.strip()[:16] or "Protagonist"]
    return [
        KernelCharacter(
            name=name,
            identifier=slugify(name),
            description=f"{name} as described in the story. Distinct silhouette.",
        )
        for name in names[:8]
    ]


def write_scene_scripts(
    story: IdeaStory,
    *,
    characters: list[KernelCharacter],
    budget: LengthBudget,
) -> list[SceneScript]:
    chunks = split_story_scenes(story.body, max_scenes=budget.max_scenes)
    if not chunks:
        chunks = [story.body or story.outline]
    names = [char.name for char in characters]
    scenes: list[SceneScript] = []
    for idx, chunk in enumerate(chunks[: budget.max_scenes]):
        if idx < len(story.scene_headings):
            heading = story.scene_headings[idx]
        else:
            heading = f"Scene {idx + 1}"
        scenes.append(
            SceneScript(
                idx=idx,
                slugline=f"INT./EXT. {heading.upper()} - DAY",
                environment=heading,
                script=chunk,
                characters=names,
            )
        )
    return scenes


def plan_idea_screenplay(
    idea: str,
    requirement: str = "",
) -> tuple[IdeaStory, list[KernelCharacter], list[SceneScript], LengthBudget]:
    budget = parse_length_budget(requirement)
    story = develop_story(idea, requirement, budget=budget)
    characters = extract_characters(story.body, idea)
    scenes = write_scene_scripts(story, characters=characters, budget=budget)
    return story, characters, scenes, budget


def _pick_tagged(requirement: str, tokens: tuple[str, ...], *, default: str) -> str:
    blob = requirement or ""
    for token in tokens:
        if token.lower() in blob.lower():
            return token
    return default
