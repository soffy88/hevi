"""创意工具动态编排(HEVI 路线图 Phase4 #45)。

9 项创意辅助工具(three-view/storyboard/story-predict/multi-angle/transition/
element-edit + 3 个 workflow)本身已经是 MCP creative 组里 agent 可调用的形态
(见 hevi.creative.assist_service / hevi.api.routers.creative),**零新增开发**。
这里补的只是"决策权从用户菜单转给 Director"这一层:给一次 LLM 调用喂 topic +
工具清单,让它判断这次要不要用、用哪个,而不是要求用户自己在 9 个选项里手动挑。

大多数题材不需要任何创意辅助工具——checklist 式判断,默认空列表,不为了"展示
编排能力"就硬凑一个用不上的工具。

只有 three-view(角色三视图)的调用参数能从 plan_from_text 已有的 topic/style
干净地推导出来,故这里做到"推荐了就真的调"；其余 8 项目前只做**推荐**(附在
输出里供前端/未来迭代消费),不强行为每个工具都编造一套参数合成逻辑——那些
工具的参数(如 script_text/reference_image/elements 列表)不是从一句 topic 就能
可靠推出来的。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

CREATIVE_TOOL_IDS: dict[str, str] = {
    "three-view": "为主角生成三视图(正/侧/背面描述),topic 涉及需要多角度一致性的具体角色时有用",
    "storyboard": "把一段剧本文本拆成分镜网格描述",
    "story-predict": "给一张参考图预测故事前后走向",
    "multi-angle": "给一个主体生成多个观察角度的描述",
    "transition": "生成两帧之间的转场视频",
    "element-edit": "编辑已有镜头列表里的元素(替换/插入/删除)",
    "workflow/character-consistency": "角色一致性工作流(多镜头保持同一角色)",
    "workflow/storyboard": "分镜工作流(端到端从剧本到分镜)",
    "workflow/comic-to-animation": "漫画/静态图转动画工作流",
}

_ORCHESTRATION_PROMPT = """下面是一个视频制作题材,和一份可用的创意辅助工具清单。
判断这个题材需不需要用到其中任何工具——大多数普通题材(比如泛泛的风景/日常
场景)不需要任何工具,只有题材明确涉及"需要多角度一致性的具体角色"、"要把
一段剧本拆分镜"这类情况才需要,不要为了展示而硬推荐。

题材:{topic}

可用工具(id: 说明):
{tool_list}

只输出 JSON 数组(可以是空数组 []):[{{"tool_id": "...", "reason": "..."}}]"""


async def recommend_creative_tools(topic: str, *, llm: Any = None) -> list[dict[str, str]]:
    """topic → 建议调用的创意工具列表(可能为空)。

    best-effort:llm 不可用/调用失败/解析失败 → 空列表,不阻断规划主流程——这是
    锦上添花的编排建议,不是必需路径。
    """
    if not topic.strip():
        return []
    if llm is None:
        try:
            from obase.provider_registry import ProviderRegistry

            llm = ProviderRegistry.get().llm("default")
        except Exception as e:
            logger.warning("creative_orchestration: no LLM available, skip: %s", e)
            return []

    tool_list = "\n".join(f"- {tid}: {desc}" for tid, desc in CREATIVE_TOOL_IDS.items())
    try:
        resp = await llm(
            messages=[
                {
                    "role": "user",
                    "content": _ORCHESTRATION_PROMPT.format(topic=topic, tool_list=tool_list),
                }
            ],
            max_tokens=512,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        m = re.search(r"\[.*\]", content, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group(0))
        if not isinstance(data, list):
            return []
        return [
            {"tool_id": str(item["tool_id"]), "reason": str(item.get("reason", ""))}
            for item in data
            if isinstance(item, dict) and item.get("tool_id") in CREATIVE_TOOL_IDS
        ]
    except Exception as e:
        logger.warning("creative_orchestration: recommendation failed, skip: %s", e)
        return []


async def apply_three_view_if_recommended(
    recommendations: list[dict[str, str]],
    *,
    topic: str,
    style: str,
    assist_service: Any = None,
) -> dict[str, Any] | None:
    """推荐列表里有 three-view 且给了 assist_service → 真的调一次(唯一一个参数能
    从 topic/style 干净推导出来的工具),返回 ThreeViewResult 的 dict 形式;没推荐/
    没给 assist_service/调用失败 → None,不阻断规划。"""
    if assist_service is None:
        return None
    if not any(r["tool_id"] == "three-view" for r in recommendations):
        return None
    try:
        result = await assist_service.gen_three_view(character_description=topic, style=style)
        return result.model_dump() if hasattr(result, "model_dump") else dict(result)
    except Exception as e:
        logger.warning("creative_orchestration: three-view invocation failed, skip: %s", e)
        return None
