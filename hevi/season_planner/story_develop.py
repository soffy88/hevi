"""故事开发阶段——对标 drama-skills short-drama-develop。

将 raw_text + production_form + genre 发展为:
- StoryBrief(创作简报):主题、冲突引擎、人物压力、升级机制
- EpisodeMap(分集地图):每集目标、阻力、因果、钩子
- DirectorBrief(导演阐述):视觉方向、生产形态约束

在 StoryGraph 抽取之前运行,为下游抽取和规划提供创作上下文。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Awaitable

from hevi.season_planner.schemas import (
    DirectorBrief,
    EpisodeMapEntry,
    ProductionForm,
    StoryBrief,
)

logger = logging.getLogger(__name__)

# ── Prompt 模板 ────────────────────────────────────────────────────────────

_DEVELOP_PROMPT = """你是一个专业的短剧/漫剧编剧顾问。请根据以下材料,产出结构化的故事开发文档。

## 输入材料

标题: {source_name}
生产形态: {production_form_label}
题材: {genre}
原始文本(摘要前 3000 字):
---
{text_preview}
---

## 请输出以下 JSON 结构(不要输出其他内容):

```json
{{
  "story_brief": {{
    "theme": "核心主题(一句话)",
    "conflict_engine": "冲突引擎描述:压力如何出现→主角如何应对→对手如何反制",
    "character_pressures": {{"角色名": "该角色面临的核心压力", ...}},
    "escalation_mechanism": "每轮冲突改变什么,而非如何重复",
    "termination_conditions": "什么变化会终结这个引擎",
    "audience_payoff": "观众反复获得的情绪/信息/权力回报"
  }},
  "episode_map": [
    {{
      "ep_number": 1,
      "entering_state": "进入状态",
      "goal": "本集目标",
      "resistance": "阻力/对抗",
      "causal_escalation": "相比上集的变化",
      "turning_point": "方向性转折",
      "payoff": "本集兑现的回报",
      "outgoing_pressure": "留给下集的压力",
      "hook": "集尾钩子"
    }}
  ],
  "director_brief": {{
    "visual_direction": "视觉方向概述",
    "tone": "情感基调",
    "pacing": "叙事节奏",
    "visual_constraints": ["约束1", "约束2"]
  }}
}}
```

## 注意事项

1. 每集必须产生局部戏剧结果(不能只铺垫不兑现)
2. 相邻集之间必须精确交接(上集 outgoing = 下集 entering_state)
3. 冲突升级要改变状态(权力/信息/关系/资源),不是单纯加大力度
4. 钩子类型由你决定(悬念/反转/危机/揭秘),但每集都要有
5. 生产形态 "{production_form_label}" 影响视觉约束的可行性
"""

_PRODUCTION_FORM_LABELS = {
    ProductionForm.LIVE_ACTION.value: "真人实拍(电影级摄影,真实场景)",
    ProductionForm.DYNAMIC_COMIC_2D.value: "2D 动态漫/漫剧(漫画风格,动态分镜)",
    ProductionForm.STYLIZED_3D.value: "风格化 3D 动画(3D 渲染,非写实)",
    ProductionForm.INKWASH.value: "水墨动画(中国传统水墨画风)",
}


async def develop_story(
    *,
    source_name: str,
    raw_text: str,
    production_form: str = "live_action",
    genre: str | None = None,
    target_episodes: int = 3,
    visual_direction: str | None = None,
    llm: Callable[..., Awaitable[str]] | None = None,
) -> tuple[StoryBrief, list[EpisodeMapEntry], DirectorBrief]:
    """故事开发主入口。

    Args:
        source_name: 材料标题
        raw_text: 原始文本
        production_form: 生产形态枚举值
        genre: 题材标签
        target_episodes: 目标集数
        visual_direction: 可选视觉方向(传入则覆盖 LLM 生成)
        llm: 可选 LLM 函数(默认用 qwen_cloud)

    Returns:
        (StoryBrief, list[EpisodeMapEntry], DirectorBrief)
    """
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("qwen_cloud")

    # 截断文本避免 LLM 超长
    text_preview = raw_text[:3000] if len(raw_text) > 3000 else raw_text
    form_label = _PRODUCTION_FORM_LABELS.get(production_form, production_form)

    prompt = _DEVELOP_PROMPT.format(
        source_name=source_name,
        production_form_label=form_label,
        genre=genre or "未指定",
        text_preview=text_preview,
    )

    try:
        raw_response = await llm(prompt)
        # 提取 JSON(处理可能的 markdown 代码块包裹)
        json_str = raw_response.strip()
        if json_str.startswith("```"):
            # 去掉 ```json ... ```
            lines = json_str.split("\n")
            json_str = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            json_str = json_str.strip()

        data = json.loads(json_str)

        brief = StoryBrief(**data.get("story_brief", {}))

        episode_map = [
            EpisodeMapEntry(**ep)
            for ep in data.get("episode_map", [])
        ]
        # 确保集数与目标一致
        while len(episode_map) < target_episodes:
            ep_num = len(episode_map) + 1
            episode_map.append(
                EpisodeMapEntry(
                    ep_number=ep_num,
                    entering_state="(待补充)",
                    goal="(待补充)",
                    hook="(待补充)",
                )
            )
        episode_map = episode_map[:target_episodes]

        director_data = data.get("director_brief", {})
        if visual_direction:
            director_data["visual_direction"] = visual_direction
        director_data["production_form"] = production_form
        director_brief = DirectorBrief(**director_data)

        logger.info(
            "story_develop %s: brief OK, %d episodes mapped",
            source_name,
            len(episode_map),
        )
        return brief, episode_map, director_brief

    except json.JSONDecodeError as e:
        logger.warning("story_develop %s: LLM 返回非法 JSON, 使用降级结果: %s", source_name, e)
        return _fallback_develop(source_name, production_form, target_episodes, visual_direction)
    except Exception as e:
        logger.exception("story_develop %s: 开发失败, 使用降级结果: %s", source_name, e)
        return _fallback_develop(source_name, production_form, target_episodes, visual_direction)


def _fallback_develop(
    source_name: str,
    production_form: str,
    target_episodes: int,
    visual_direction: str | None = None,
) -> tuple[StoryBrief, list[EpisodeMapEntry], DirectorBrief]:
    """LLM 调用失败时的降级结果:最小可用结构,不阻塞下游。"""
    brief = StoryBrief(
        theme="(待开发)",
        conflict_engine="(待开发)",
        escalation_mechanism="(待开发)",
    )

    episode_map = [
        EpisodeMapEntry(
            ep_number=i + 1,
            entering_state="(待开发)",
            goal="(待开发)",
            hook="(待开发)",
        )
        for i in range(target_episodes)
    ]

    director_brief = DirectorBrief(
        visual_direction=visual_direction or "(待开发)",
        production_form=production_form,
    )

    return brief, episode_map, director_brief
