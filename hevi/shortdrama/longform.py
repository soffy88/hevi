"""长篇短剧规划链入口（DRAMAPLAN P3）。

将长篇小说文本整合成完整的制作分镜：
长篇文本 → 章节事件图(含长记忆) → 改编大纲 → 三层审稿互审 → 镜头级分镜脚本。
不要求出视频，不调付费视频供应商。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hevi.memory.store import MemoryStore
from hevi.storygraph.chapters import (
    build_adaptation_outline,
    build_book_event_graph,
)
from hevi.storygraph.review import (
    DEFAULT_TABOO_KEYWORDS,
    ReviewLog,
    run_three_layer_review,
    script_to_storyboard,
    write_review_log,
)
from hevi.storygraph.schemas import (
    AdaptationOutline,
    EpisodeStoryboard,
    StoryGraph,
)

logger = logging.getLogger(__name__)


class LongformDramaPlan(BaseModel):
    """长篇短剧全链路规划产物。"""

    source_name: str
    target_episodes: int
    episode_duration_s: float
    total_shot_budget: int
    event_graph: StoryGraph
    outline: AdaptationOutline
    review_log: ReviewLog
    storyboards: list[EpisodeStoryboard] = Field(default_factory=list)

    def total_shots(self) -> int:
        return sum(sb.total_shots() for sb in self.storyboards)

    def total_duration(self) -> float:
        return sum(sb.total_duration() for sb in self.storyboards)

    def save(self, output_dir: str | Path) -> dict[str, Path]:
        """将全链路规划产物结构化落盘（方便 CLI、生产排期与 E2E 校验）。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}

        # 1. event_graph.json
        eg_path = out / "event_graph.json"
        eg_path.write_text(self.event_graph.model_dump_json(indent=2), encoding="utf-8")
        paths["event_graph"] = eg_path

        # 2. adaptation_outline.json
        ao_path = out / "adaptation_outline.json"
        ao_path.write_text(self.outline.model_dump_json(indent=2), encoding="utf-8")
        paths["adaptation_outline"] = ao_path

        # 3. review_log.json
        rl_path = out / "review_log.json"
        write_review_log(self.review_log, rl_path)
        paths["review_log"] = rl_path

        # 4. storyboards/epXX.json
        sb_dir = out / "storyboards"
        sb_dir.mkdir(parents=True, exist_ok=True)
        for sb in self.storyboards:
            p = sb_dir / f"ep{sb.ep_number:02d}.json"
            p.write_text(sb.model_dump_json(indent=2), encoding="utf-8")
            paths[f"storyboard_ep{sb.ep_number:02d}"] = p

        return paths


async def plan_longform_drama(
    source_name: str,
    raw_text: str,
    *,
    target_episodes: int = 3,
    episode_duration_s: float = 60.0,
    llm: Any = None,
    memory_store: MemoryStore | None = None,
    max_review_rounds: int = 2,
    taboo_keywords: tuple[str, ...] = DEFAULT_TABOO_KEYWORDS,
    on_step: Any = None,
) -> LongformDramaPlan:
    """长篇小说短剧规划主入口：长篇文本 → 事件图 → 大纲 → 三层审稿 → 镜头分镜。

    一条链调用，产出镜头级分镜，各镜头可直接转换为 `oskill.ShotPlan`。
    """
    logger.info(
        "开始长篇短剧规划: source=%s, 集数=%d, 单集时长=%.1fs",
        source_name,
        target_episodes,
        episode_duration_s,
    )

    # 1. 抽取章节事件图（自动接入前文记忆检索与跨章缝合）
    book = await build_book_event_graph(
        source_name=source_name,
        raw_text=raw_text,
        llm=llm,
        memory_store=memory_store,
    )

    # 2. 生成多集改编大纲（严格保证每集与总预算一致）
    outline = build_adaptation_outline(
        book,
        target_episodes=target_episodes,
        episode_duration_s=episode_duration_s,
    )

    # 3. 运行三层审稿回路（决策 → 执行 → 监督 → 针对性 LLM 返修）
    review_log = await run_three_layer_review(
        book,
        outline,
        llm=llm,
        max_rounds=max_review_rounds,
        taboo_keywords=taboo_keywords,
        on_step=on_step,
    )

    # 4. 从审稿通过剧本派生镜头级分镜
    outline_by_ep = {ep.ep_number: ep for ep in outline.episodes}
    storyboards: list[EpisodeStoryboard] = []
    for ep_review in review_log.episodes:
        outline_ep = outline_by_ep.get(ep_review.ep_number)
        sb = script_to_storyboard(ep_review.script, book, outline_ep=outline_ep)
        storyboards.append(sb)

    return LongformDramaPlan(
        source_name=source_name,
        target_episodes=target_episodes,
        episode_duration_s=episode_duration_s,
        total_shot_budget=outline.total_shot_budget,
        event_graph=book,
        outline=outline,
        review_log=review_log,
        storyboards=storyboards,
    )
