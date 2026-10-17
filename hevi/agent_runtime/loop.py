"""
Agent Loop（对标 ViMax loop.py）

自主 Agent 循环：LLM 调用工具 → 执行工具 → 结果反馈 → 再调 LLM → ... 直到完成。

核心特性：
  - 流式事件协议（turn/token/tool_start/tool_progress/tool_result/status/done/error）
  - MAX_TOOL_PASSES=50 安全阀
  - 进度队列（工具通过 async queue 上报进度）
  - 与 SessionIndex + ContextCompactor 集成
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Awaitable,
    Dict,
    List,
    Optional,
    Protocol,
)

from hevi.agent_runtime.session import SessionIndex, TurnRecord
from hevi.agent_runtime.compactor import ContextCompactor

logger = logging.getLogger(__name__)


# ── 事件类型 ──────────────────────────────────────────────────────────


@dataclass
class AgentEvent:
    """Agent 事件"""
    type: str  # turn | token | tool_start | tool_progress | tool_result | status | done | error
    turn_id: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


# ── 工具协议 ──────────────────────────────────────────────────────────


@dataclass
class ToolDefinition:
    """工具定义（OpenAI function calling schema）"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema

    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCall:
    """工具调用请求"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """工具调用结果"""
    tool_call_id: str
    name: str
    output: Any
    ok: bool = True
    error: str = ""


# 工具执行函数签名: (name, arguments, progress_callback) → ToolResult
ToolExecutorFn = Callable[
    [str, Dict[str, Any], Callable[[str], None]],
    Awaitable[ToolResult],
]

# LLM 调用函数签名: (messages, tools) → (text, tool_calls)
LLMCallerFn = Callable[
    [List[Dict[str, Any]], List[Dict[str, Any]]],
    Awaitable[tuple[str, List[ToolCall]]],
]


# ── 默认工具执行器 ────────────────────────────────────────────────────


class ToolRegistry:
    """工具注册表"""

    def __init__(self):
        self._tools: Dict[str, tuple[ToolDefinition, Callable]] = {}

    def register(
        self,
        name: str,
        fn: Callable,
        description: str,
        parameters: Dict[str, Any],
    ) -> None:
        """注册工具"""
        definition = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
        )
        self._tools[name] = (definition, fn)

    def get(self, name: str) -> Optional[tuple[ToolDefinition, Callable]]:
        return self._tools.get(name)

    def list_definitions(self) -> List[ToolDefinition]:
        return [defn for defn, _ in self._tools.values()]

    def to_openai_schemas(self) -> List[Dict[str, Any]]:
        return [d.to_openai_schema() for d in self.list_definitions()]

    async def execute(
        self,
        call: ToolCall,
        progress_callback: Callable[[str], None],
    ) -> ToolResult:
        """执行工具调用"""
        entry = self._tools.get(call.name)
        if not entry:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                output=None,
                ok=False,
                error=f"unknown tool: {call.name}",
            )

        _, fn = entry
        try:
            # 尝试带 progress_callback 调用
            try:
                result = await fn(**call.arguments, progress_callback=progress_callback)
            except TypeError:
                # 不支持 progress_callback，直接调用
                result = await fn(**call.arguments)

            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                output=result,
                ok=True,
            )
        except Exception as e:
            logger.error("tool %s failed: %s", call.name, e)
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                output=None,
                ok=False,
                error=str(e),
            )


# ── Agent Loop ────────────────────────────────────────────────────────


class AgentLoop:
    """
    Agent 循环

    用法：
        loop = AgentLoop(
            llm_caller=my_llm_caller,
            tool_registry=tool_registry,
            session_index=session_index,
            compactor=compactor,
        )

        async for event in loop.run(user_input="帮我生成一个视频"):
            if event.type == "done":
                print(event.data["assistant"])
            elif event.type == "error":
                print(f"Error: {event.data['message']}")
    """

    MAX_TOOL_PASSES = 50

    def __init__(
        self,
        llm_caller: LLMCallerFn,
        tool_registry: ToolRegistry,
        session_index: Optional[SessionIndex] = None,
        compactor: Optional[ContextCompactor] = None,
        system_prompt: str = "You are a helpful assistant.",
        max_tool_passes: int = 50,
        session_id: Optional[str] = None,
    ):
        self.llm_caller = llm_caller
        self.tool_registry = tool_registry
        self.session_index = session_index
        self.compactor = compactor
        self.system_prompt = system_prompt
        self.max_tool_passes = max_tool_passes
        self.session_id = session_id
        self._messages: List[Dict[str, Any]] = []

    async def run(self, user_input: str) -> AsyncIterator[AgentEvent]:
        """
        运行 Agent 循环

        产出事件流：
          turn → token* → tool_start → tool_progress* → tool_result → ... → done
        """
        turn_id = f"turn-{uuid.uuid4().hex[:8]}"

        # 发出 turn 事件
        yield AgentEvent(type="turn", turn_id=turn_id, data={"id": turn_id})

        # 初始化消息
        if not self._messages:
            self._messages = [{"role": "system", "content": self.system_prompt}]

        # 添加用户输入
        self._messages.append({"role": "user", "content": user_input})

        # 检查是否需要压缩
        if self.compactor and self.compactor.should_compact(self._messages):
            yield AgentEvent(
                type="status",
                turn_id=turn_id,
                data={"phase": "compacting", "message": "上下文过长，正在压缩..."},
            )
            try:
                result = await self.compactor.compact(self._messages)
                self._messages = [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "system", "content": f"[上下文摘要]\n{result.summary}"},
                ] + result.preserved_messages
                yield AgentEvent(
                    type="status",
                    turn_id=turn_id,
                    data={
                        "phase": "compacted",
                        "message": f"压缩完成: {result.messages_before} → {result.messages_after} 条消息",
                        "tokens_before": result.tokens_before,
                        "tokens_after": result.tokens_after,
                    },
                )
            except Exception as e:
                logger.warning("compaction failed: %s", e)

        # 工具调用循环
        tool_passes = 0
        all_tool_results: List[Dict[str, Any]] = []

        while tool_passes < self.max_tool_passes:
            tool_passes += 1

            # 调用 LLM
            yield AgentEvent(
                type="status",
                turn_id=turn_id,
                data={"phase": "sampling_assistant", "message": f"思考中... (第 {tool_passes} 轮)"},
            )

            try:
                tools_schema = self.tool_registry.to_openai_schemas()
                text, tool_calls = await self.llm_caller(self._messages, tools_schema)
            except Exception as e:
                yield AgentEvent(
                    type="error",
                    turn_id=turn_id,
                    data={"message": f"LLM 调用失败: {e}"},
                )
                return

            # 添加助手回复到消息
            assistant_msg: Dict[str, Any] = {"role": "assistant", "content": text}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": str(tc.arguments),
                        },
                    }
                    for tc in tool_calls
                ]
            self._messages.append(assistant_msg)

            # 如果没有工具调用，结束
            if not tool_calls:
                # 保存 turn 到 session
                if self.session_index and self.session_id:
                    turn_record = TurnRecord(
                        turn_id=turn_id,
                        user_input=user_input,
                        assistant_output=text,
                        tool_calls=[tc.__dict__ for tc in []],
                        tool_results=all_tool_results,
                    )
                    self.session_index.add_turn(self.session_id, turn_record)

                yield AgentEvent(
                    type="done",
                    turn_id=turn_id,
                    data={
                        "assistant": text,
                        "tool_results": all_tool_results,
                        "tool_passes": tool_passes,
                    },
                )
                return

            # 执行工具调用
            for tc in tool_calls:
                yield AgentEvent(
                    type="tool_start",
                    turn_id=turn_id,
                    data={
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "tool_call_id": tc.id,
                    },
                )

                # 进度回调
                def progress_cb(msg: str):
                    pass  # 在同步上下文中忽略

                result = await self.tool_registry.execute(tc, progress_cb)

                # 添加结果到消息
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result.output) if result.ok else f"ERROR: {result.error}",
                }
                self._messages.append(tool_msg)

                all_tool_results.append({
                    "name": tc.name,
                    "ok": result.ok,
                    "output": str(result.output)[:500],  # 截断长输出
                    "error": result.error,
                })

                yield AgentEvent(
                    type="tool_result",
                    turn_id=turn_id,
                    data={
                        "name": tc.name,
                        "ok": result.ok,
                        "output_preview": str(result.output)[:200] if result.ok else "",
                        "error": result.error,
                        "tool_call_id": tc.id,
                    },
                )

        # 超过最大轮次
        yield AgentEvent(
            type="error",
            turn_id=turn_id,
            data={
                "message": f"工具调用超过 {self.max_tool_passes} 轮，已终止",
                "tool_passes": tool_passes,
            },
        )

    async def run_once(self, user_input: str) -> str:
        """简化版：运行并返回最终文本"""
        final_text = ""
        async for event in self.run(user_input):
            if event.type == "done":
                final_text = event.data.get("assistant", "")
            elif event.type == "error":
                final_text = f"ERROR: {event.data.get('message', 'unknown')}"
        return final_text

    def reset(self) -> None:
        """重置对话历史"""
        self._messages = []

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def get_messages(self) -> List[Dict[str, Any]]:
        return list(self._messages)
