"""Public script-generation facade for Explainer Master v8 + 反压缩升级。

The provider remains injectable so research/model failures are returned as the
same structured capability errors used by the API; this module contains no
fallback or canned storyboard.

生成策略由 research dict 里的 target_duration 决定(见 hevi.explainer.research._should_chunk):
- ≤ 6 分钟(需求字数 ≤ 1500 字):单次生成,强制输出素材吸收与扩写矩阵
  (material_coverage_matrix)+ 反压缩纪律。
- > 6 分钟(需求字数 > 1500 字):分章迭代生成 —— Step A 只产出大纲与素材矩阵,
  Step B 逐章把深度扩写喂给 LLM 生成 cues,Step C 在 Python 后端合并各章 cues
  并回填矩阵,彻底突破单次 LLM 生成的字数与深度极限。
"""

from __future__ import annotations

from typing import Any

from hevi.explainer.contracts import ExplainerResearchRequest, ExplainerServiceResult
from hevi.explainer.research import research_and_generate


async def generate_script_versions(
    topic_or_url: str,
    research: dict[str, Any],
    *,
    generator: Any,
) -> ExplainerServiceResult:
    """Generate and validate exactly three visual-scaffold script versions.

    research dict 可携带 target_duration(如 "8"/"10-15"),透传给
    research_and_generate 后自动决定单次生成或分章生成。
    """
    return await research_and_generate(
        ExplainerResearchRequest(topic_or_url=topic_or_url),
        researcher=lambda _topic: research,
        script_generator=generator,
    )


__all__ = ["generate_script_versions"]
