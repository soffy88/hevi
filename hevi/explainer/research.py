"""Research + three-script generation for Explainer Master v8.

Providers are injected at this boundary.  The default implementation uses the
same configured HEVI LLM registry as the existing E0 storyboard generator;
there is deliberately no canned/fake research response when that provider is
missing or returns malformed JSON.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from hevi.explainer.contracts import (
    ExplainerCapabilityError,
    ExplainerResearchRequest,
    ExplainerScriptDraft,
    ExplainerServiceResult,
    HookDraft,
    ResearchFact,
)

logger = logging.getLogger(__name__)


class ResearchProvider(Protocol):
    async def research(self, topic_or_url: str) -> dict[str, Any]: ...


class ScriptGenerator(Protocol):
    async def generate(
        self, topic_or_url: str, research: dict[str, Any]
    ) -> dict[str, Any]: ...


ResearchCallable = Callable[[str], Awaitable[dict[str, Any]] | dict[str, Any]]
ScriptCallable = Callable[
    [str, dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]
]


_JSON_PROMPT = """你是 HEVI 深度解说研究与脚本编剧。对下面选题做可核验的资料提炼，
并给出恰好 5 个不同抓手和恰好 3 个结构化脚本版本。不要编造来源；无法核验的事实
请降低 confidence 并明确 source 为空。每个脚本必须有可编辑的 visual scaffold cues。

选题或材料：{topic}

只返回 JSON，不要 markdown：
{{
  "research_summary": "用一段话概括调研结论",
  "facts": [{{"claim":"...","source":"...","confidence":0.0}}],
  "hooks": [{{"text":"...","angle":"...","recommended":true}}],
  "scripts": [{{"id":"A","title":"...","viewpoint":"...","hook":"...",
    "cues":[{{"step_id":1,"visual_type":"heygen_avatar","text":"...","time_estimate_s":4.5}},
             {{"step_id":2,"visual_type":"browser_broll","target_url":"https://example.gov.cn/report","highlight_selector":".data-table","text":"...","time_estimate_s":8}},
             {{"step_id":3,"visual_type":"remotion_chart","chart_data":{{"type":"bar","labels":[],"values":[]}},"text":"...","time_estimate_s":6}}]}}]
}}"""


def _extract_json(content: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", "模型没有返回可解析的研究 JSON"
        )
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", f"模型研究 JSON 无法解析: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "模型研究结果不是 JSON 对象")
    return value


async def _invoke(provider: Any, *args: Any, **kwargs: Any) -> Any:
    result = provider(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _default_llm() -> Any:
    try:
        from obase.provider_registry import ProviderRegistry

        return ProviderRegistry.get().llm("default")
    except Exception as exc:  # pragma: no cover - depends on deployment
        raise ExplainerCapabilityError(
            "CAPABILITY_UNAVAILABLE",
            "研究模型不可用：未配置默认 LLM Provider",
            action="配置 ProviderRegistry 的 default LLM 后重试",
        ) from exc


async def _llm_research(topic_or_url: str) -> dict[str, Any]:
    llm = _default_llm()
    try:
        response = await _invoke(
            llm,
            messages=[{"role": "user", "content": _JSON_PROMPT.format(topic=topic_or_url)}],
            max_tokens=8_000,
            result_format="json",
        )
    except ExplainerCapabilityError:
        raise
    except Exception as exc:
        raise ExplainerCapabilityError(
            "CAPABILITY_UNAVAILABLE",
            f"研究模型调用失败: {exc}",
            action="检查 LLM Provider 健康状态",
        ) from exc
    content = response.get("content") if isinstance(response, dict) else str(response)
    if not isinstance(content, str) or not content.strip():
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "研究模型返回空正文")
    return _extract_json(content)


async def _mcp_research(topic_or_url: str) -> dict[str, Any] | None:
    """Use a registered GPT Researcher MCP client when deployment provides it."""
    try:
        from obase.mcp_client import McpClientRegistry

        client_name = os.environ.get("HEVI_EXPLAINER_RESEARCH_MCP", "gpt_researcher")
        client = McpClientRegistry.get(client_name)
    except (ImportError, KeyError):
        return None
    try:
        tools = await client.list_tools()
        names = {
            str(tool.get("name"))
            for tool in tools
            if isinstance(tool, dict) and tool.get("name")
        }
        tool_name = next(
            (name for name in ("research", "deep_research", "gpt_research") if name in names),
            None,
        )
        if tool_name is None:
            raise ExplainerCapabilityError(
                "CAPABILITY_UNAVAILABLE", "GPT Researcher MCP 未暴露 research 工具"
            )
        result = await client.call_tool(
            tool_name,
            {"query": topic_or_url, "topic": topic_or_url, "max_sources": 8},
        )
        if isinstance(result, dict):
            return result
        content = getattr(result, "text", None) or getattr(result, "content", None)
        if isinstance(content, str):
            return _extract_json(content)
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "GPT Researcher MCP 返回格式错误")
    except ExplainerCapabilityError:
        raise
    except Exception as exc:
        raise ExplainerCapabilityError(
            "CAPABILITY_UNAVAILABLE", f"GPT Researcher MCP 调用失败: {exc}"
        ) from exc


async def _call_provider(provider: Any, topic_or_url: str) -> dict[str, Any]:
    if hasattr(provider, "research"):
        value = await _invoke(provider.research, topic_or_url)
    else:
        value = await _invoke(provider, topic_or_url)
    if not isinstance(value, dict):
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "调研 Provider 返回格式错误")
    return value


def _normalise(raw: dict[str, Any], topic_or_url: str, provider: str) -> ExplainerServiceResult:
    try:
        facts = [
            ResearchFact.model_validate(item if isinstance(item, dict) else {"claim": str(item)})
            for item in raw.get("facts", [])
        ]
        hooks = [
            HookDraft.model_validate(item if isinstance(item, dict) else {"text": str(item)})
            for item in raw.get("hooks", [])
        ]
        scripts = [ExplainerScriptDraft.model_validate(item) for item in raw.get("scripts", [])]
    except Exception as exc:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", f"研究脚本字段校验失败: {exc}"
        ) from exc
    if len(hooks) != 5:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", f"研究结果必须包含 5 个 Hook，实际 {len(hooks)} 个"
        )
    if len(scripts) != 3:
        raise ExplainerCapabilityError(
            "MODEL_OUTPUT_INVALID", f"研究结果必须包含 3 个脚本版本，实际 {len(scripts)} 个"
        )
    for script in scripts:
        if not script.cues:
            raise ExplainerCapabilityError(
                "MODEL_OUTPUT_INVALID", f"脚本 {script.id} 缺少视觉脚手架"
            )
    summary = str(raw.get("research_summary") or "；".join(
        fact.claim for fact in facts[:5]
    ))
    return ExplainerServiceResult(
        facts=facts,
        research_summary=summary,
        hooks=hooks,
        scripts=scripts,
        provider=provider,
        decision_trail=[
            {"stage": "research", "provider": provider, "outcome": "completed"},
            {"stage": "script_generation", "script_count": 3, "outcome": "completed"},
        ],
    )


async def research_and_generate(
    request: ExplainerResearchRequest,
    *,
    researcher: Any = None,
    script_generator: Any = None,
) -> ExplainerServiceResult:
    """Run research and script generation with explicit provider errors."""
    if researcher is None and script_generator is None:
        mcp_result = await _mcp_research(request.topic_or_url)
        raw = mcp_result if mcp_result is not None else await _llm_research(request.topic_or_url)
        provider = (
            "obase.mcp.gpt_researcher"
            if mcp_result is not None
            else "provider_registry.default"
        )
        return _normalise(raw, request.topic_or_url, provider)

    if researcher is None:
        raise ExplainerCapabilityError(
            "CAPABILITY_UNAVAILABLE",
            "调研 Provider 未注入",
            action="配置 GPT Researcher MCP Provider",
        )
    research = await _call_provider(researcher, request.topic_or_url)
    generated = research
    if script_generator is not None:
        if hasattr(script_generator, "generate"):
            generated = await _invoke(
                script_generator.generate, request.topic_or_url, research
            )
        else:
            generated = await _invoke(script_generator, request.topic_or_url, research)
    if not isinstance(generated, dict):
        raise ExplainerCapabilityError("MODEL_OUTPUT_INVALID", "脚本生成器返回格式错误")
    if "facts" not in generated:
        generated = {**research, **generated}
    return _normalise(generated, request.topic_or_url, "injected")


def response_payload(result: ExplainerServiceResult, topic_or_url: str) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    payload["topic_or_url"] = topic_or_url
    payload["script_versions"] = payload["scripts"]
    payload["hook_details"] = payload["hooks"]
    payload["hooks"] = [hook["text"] for hook in payload["hooks"]]
    return payload
