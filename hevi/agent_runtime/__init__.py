"""
Agent Runtime（对标 ViMax agent_runtime/）

提供自主 Agent 循环的基础设施：
  - loop: Agent Loop（工具调用 + 流式事件 + 安全阀）
  - compactor: 上下文压缩器（token 阈值自动压缩）
  - session: 会话持久化（Session Index）
  - checkpoint: 管线检查点（artifact 断点续跑）
  - prompt_builder: Prompt 构建器（统一 prompt 构建系统）
"""
from hevi.agent_runtime.loop import (
    AgentEvent,
    AgentLoop,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
)
from hevi.agent_runtime.compactor import (
    CompactionResult,
    ContextCompactor,
)
from hevi.agent_runtime.session import (
    CompactionRecord,
    SessionIndex,
    SessionMetadata,
    TurnRecord,
)
from hevi.agent_runtime.checkpoint import (
    ArtifactMetadata,
    CheckpointedPipeline,
    PipelineCheckpoint,
    StageConfig,
)
from hevi.agent_runtime.prompt_builder import (
    PromptBuilder,
    PromptContext,
    PromptPart,
    ToolInfo,
    build_pipeline_prompt,
    build_vimax_agent_prompt,
)

__all__ = [
    # Loop
    "AgentEvent",
    "AgentLoop",
    "ToolCall",
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    # Compactor
    "CompactionResult",
    "ContextCompactor",
    # Session
    "CompactionRecord",
    "SessionIndex",
    "SessionMetadata",
    "TurnRecord",
    # Checkpoint
    "ArtifactMetadata",
    "CheckpointedPipeline",
    "PipelineCheckpoint",
    "StageConfig",
    # Prompt Builder
    "PromptBuilder",
    "PromptContext",
    "PromptPart",
    "ToolInfo",
    "build_pipeline_prompt",
    "build_vimax_agent_prompt",
]
