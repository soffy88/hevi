"""多 Agent 编排框架 — 对标 OpenManus。

支持多步视频制作任务的 Agent 编排:
- ReAct 模式 (推理 + 行动)
- 工具调用 (Tool-use)
- 多 Agent 协作 (并行/串行/DAG)
- 状态追踪 + 重试

参考: https://github.com/FoundationAgents/OpenManus
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "AgentRole",
    "ToolCall",
    "ToolResult",
    "AgentStep",
    "AgentTask",
    "AgentPlan",
    "AgentState",
    "AgentOrchestrator",
    "create_video_plan",
]


class AgentRole(str, Enum):
    planner = "planner"
    script_writer = "script_writer"
    voice_synthesizer = "voice_synthesizer"
    video_generator = "video_generator"
    editor = "editor"
    publisher = "publisher"
    reviewer = "reviewer"


class AgentState(str, Enum):
    pending = "pending"
    thinking = "thinking"
    acting = "acting"
    observing = "observing"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_call_id: str = ""
    success: bool = True
    output: Any = None
    error: Optional[str] = None


class AgentStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    role: AgentRole = AgentRole.planner
    state: AgentState = AgentState.pending
    thought: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    observations: list[ToolResult] = Field(default_factory=list)
    output: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str = ""
    steps: list[AgentStep] = Field(default_factory=list)
    state: AgentState = AgentState.pending
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentPlan(BaseModel):
    """多 Agent 协作计划 (DAG)。"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    description: str = ""
    tasks: list[AgentTask] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)  # task_id → [depends_on_ids]
    parallel_groups: list[list[str]] = Field(default_factory=list)  # 可并行的任务组


class AgentOrchestrator:
    """Agent 编排器。"""

    def __init__(self):
        self._plans: dict[str, AgentPlan] = {}
        self._tools: dict[str, Callable] = {}

    def register_tool(self, name: str, func: Callable) -> None:
        self._tools[name] = func

    def register_plan(self, plan: AgentPlan) -> str:
        self._plans[plan.id] = plan
        return plan.id

    async def execute_plan(self, plan_id: str) -> AgentPlan | None:
        plan = self._plans.get(plan_id)
        if not plan:
            return None

        logger.info("Executing plan: %s (%d tasks)", plan.name, len(plan.tasks))

        # Topological execution
        completed: set[str] = set()
        task_map = {t.id: t for t in plan.tasks}

        while len(completed) < len(plan.tasks):
            # Find ready tasks (all deps completed)
            ready = []
            for task in plan.tasks:
                if task.id in completed or task.state == AgentState.completed:
                    continue
                deps = plan.dependencies.get(task.id, [])
                if all(d in completed for d in deps):
                    ready.append(task)

            if not ready:
                break  # Deadlock or all done

            # Execute ready tasks (parallel if possible)
            for task in ready:
                await self._execute_task(task)
                if task.state == AgentState.completed:
                    completed.add(task.id)

        return plan

    async def _execute_task(self, task: AgentTask) -> None:
        task.state = AgentState.thinking
        logger.info("Task [%s] %s: thinking...", task.id, task.description[:50])

        for step in task.steps:
            step.state = AgentState.acting
            step.started_at = datetime.utcnow()

            # Execute tool calls
            for call in step.tool_calls:
                tool = self._tools.get(call.tool_name)
                if tool:
                    try:
                        result = await tool(**call.arguments) if asyncio.iscoroutinefunction(tool) else tool(**call.arguments)
                        step.observations.append(ToolResult(
                            tool_call_id=call.id, output=result,
                        ))
                    except Exception as e:
                        step.observations.append(ToolResult(
                            tool_call_id=call.id, success=False, error=str(e),
                        ))

            step.state = AgentState.completed
            step.completed_at = datetime.utcnow()

        task.state = AgentState.completed


def create_video_plan(
    script: str,
    style: str = "default",
    platforms: list[str] | None = None,
) -> AgentPlan:
    """创建视频制作计划。

    典型流程: 写脚本 → 生成语音 → 生成视频 → 剪辑 → 发布
    """
    plan = AgentPlan(
        name="video_production",
        description=f"从脚本到成片: {script[:50]}...",
    )

    # Task 1: Script
    t_script = AgentTask(
        description="编写/优化脚本",
        steps=[AgentStep(
            role=AgentRole.script_writer,
            tool_calls=[ToolCall(tool_name="llm_rewrite", arguments={"text": script, "style": style})],
        )],
    )

    # Task 2: Voice
    t_voice = AgentTask(
        description="语音合成",
        steps=[AgentStep(
            role=AgentRole.voice_synthesizer,
            tool_calls=[ToolCall(tool_name="tts_synthesize", arguments={"text": script})],
        )],
    )

    # Task 3: Video
    t_video = AgentTask(
        description="视频生成",
        steps=[AgentStep(
            role=AgentRole.video_generator,
            tool_calls=[ToolCall(tool_name="video_generate", arguments={"script": script})],
        )],
    )

    # Task 4: Edit
    t_edit = AgentTask(
        description="剪辑合成",
        steps=[AgentStep(
            role=AgentRole.editor,
            tool_calls=[ToolCall(tool_name="video_assemble", arguments={})],
        )],
    )

    # Task 5: Publish (optional)
    tasks = [t_script, t_voice, t_video, t_edit]
    deps = {
        t_voice.id: [t_script.id],
        t_video.id: [t_voice.id],
        t_edit.id: [t_video.id],
    }

    if platforms:
        t_publish = AgentTask(
            description=f"发布到 {', '.join(platforms)}",
            steps=[AgentStep(
                role=AgentRole.publisher,
                tool_calls=[ToolCall(tool_name="publish_video", arguments={"platforms": platforms})],
            )],
        )
        tasks.append(t_publish)
        deps[t_publish.id] = [t_edit.id]

    plan.tasks = tasks
    plan.dependencies = deps
    plan.parallel_groups = [[t_script.id], [t_voice.id, t_video.id], [t_edit.id]]

    return plan
