"""Prompt Builder — 统一 prompt 构建系统（对标 ViMax prompt_builder.py）。

组合多个 prompt 来源为完整的 system prompt：
  1. 基础 prompt 模板（agent.md / workflow.md）
  2. 会话上下文（active session / artifacts / checklist）
  3. 工具列表（可用工具描述）
  4. 用户自定义指令

支持：
  - 模板变量替换
  - 动态上下文注入
  - 多语言 prompt
  - prompt 版本管理
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class PromptPart:
    """Prompt 组成部分。"""

    name: str
    content: str
    priority: int = 0  # 越高越靠前
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content[:200],  # 截断
            "priority": self.priority,
            "enabled": self.enabled,
        }


@dataclass
class PromptContext:
    """Prompt 上下文（动态注入的信息）。"""

    session_id: str = ""
    project_name: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    previous_summary: str = ""
    custom_instructions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "project_name": self.project_name,
            "artifact_count": len(self.artifacts),
            "checklist_count": len(self.checklist),
            "has_summary": bool(self.previous_summary),
        }


@dataclass
class ToolInfo:
    """工具信息（用于 prompt 中的工具列表）。"""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_prompt_text(self) -> str:
        """转换为 prompt 文本。"""
        lines = [f"### {self.name}", self.description]
        if self.parameters:
            lines.append("**参数**:")
            for param_name, param_info in self.parameters.items():
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                required = param_info.get("required", False)
                req_mark = " (必需)" if required else ""
                lines.append(f"- `{param_name}` ({param_type}){req_mark}: {param_desc}")
        return "\n".join(lines)


# ── Prompt Builder ────────────────────────────────────────────────────


class PromptBuilder:
    """Prompt 构建器。

    用法：
        builder = PromptBuilder()
        builder.add_template("你是 Hevi 视频生成助手...")
        builder.set_context(PromptContext(session_id="abc123"))
        builder.add_tools([ToolInfo("generate_video", "生成视频", {...})])

        system_prompt = builder.build()
    """

    def __init__(self):
        self._parts: list[PromptPart] = []
        self._context: PromptContext | None = None
        self._tools: list[ToolInfo] = []
        self._variables: dict[str, str] = {}

    def add_template(
        self,
        content: str,
        name: str = "base_template",
        priority: int = 100,
    ) -> "PromptBuilder":
        """添加基础模板。

        Args:
            content: 模板内容（支持 {variable} 占位符）
            name: 模板名称
            priority: 优先级（越高越靠前）

        Returns:
            self（链式调用）
        """
        self._parts.append(PromptPart(
            name=name,
            content=content,
            priority=priority,
        ))
        return self

    def load_template(
        self,
        path: Path,
        name: str | None = None,
        priority: int = 100,
    ) -> "PromptBuilder":
        """从文件加载模板。

        Args:
            path: 模板文件路径（.md 或 .txt）
            name: 模板名称（默认用文件名）
            priority: 优先级

        Returns:
            self
        """
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")

        content = path.read_text(encoding="utf-8")
        template_name = name or path.stem
        return self.add_template(content, template_name, priority)

    def set_context(self, context: PromptContext) -> "PromptBuilder":
        """设置动态上下文。

        Args:
            context: 会话上下文

        Returns:
            self
        """
        self._context = context
        return self

    def add_tools(self, tools: list[ToolInfo]) -> "PromptBuilder":
        """添加工具列表。

        Args:
            tools: 工具信息列表

        Returns:
            self
        """
        self._tools.extend(tools)
        return self

    def set_variable(self, key: str, value: str) -> "PromptBuilder":
        """设置模板变量。

        Args:
            key: 变量名（不带花括号）
            value: 变量值

        Returns:
            self
        """
        self._variables[key] = value
        return self

    def set_variables(self, variables: dict[str, str]) -> "PromptBuilder":
        """批量设置模板变量。"""
        self._variables.update(variables)
        return self

    def build(self, user_input: str = "") -> str:
        """构建完整的 system prompt。

        Args:
            user_input: 用户输入（可选，用于动态调整 prompt）

        Returns:
            完整的 system prompt 字符串
        """
        parts: list[str] = []

        # 1. 基础模板（按优先级排序）
        sorted_parts = sorted(
            [p for p in self._parts if p.enabled],
            key=lambda p: p.priority,
            reverse=True,
        )
        for part in sorted_parts:
            content = part.content
            # 变量替换
            for key, value in self._variables.items():
                content = content.replace(f"{{{key}}}", value)
            parts.append(content)

        # 2. 上下文信息
        if self._context:
            context_text = self._build_context_section()
            if context_text:
                parts.append(context_text)

        # 3. 工具列表
        if self._tools:
            tools_text = self._build_tools_section()
            parts.append(tools_text)

        # 4. 用户输入提示（如果有）
        if user_input:
            parts.append(f"\n\n## 用户请求\n{user_input}")

        return "\n\n".join(parts)

    def _build_context_section(self) -> str:
        """构建上下文部分。"""
        if not self._context:
            return ""

        lines = ["## 当前上下文"]

        if self._context.session_id:
            lines.append(f"- **会话 ID**: {self._context.session_id}")
        if self._context.project_name:
            lines.append(f"- **项目名称**: {self._context.project_name}")

        # 摘要
        if self._context.previous_summary:
            lines.append(f"\n### 之前对话摘要\n{self._context.previous_summary}")

        # Artifacts
        if self._context.artifacts:
            lines.append("\n### 已生成的 Artifacts")
            for artifact in self._context.artifacts:
                name = artifact.get("name", "unnamed")
                path = artifact.get("path", "")
                lines.append(f"- {name}: `{path}`")

        # Checklist
        if self._context.checklist:
            lines.append("\n### 待办清单")
            for i, item in enumerate(self._context.checklist, 1):
                lines.append(f"{i}. {item}")

        # 自定义指令
        if self._context.custom_instructions:
            lines.append("\n### 自定义指令")
            for instr in self._context.custom_instructions:
                lines.append(f"- {instr}")

        return "\n".join(lines)

    def _build_tools_section(self) -> str:
        """构建工具列表部分。"""
        if not self._tools:
            return ""

        lines = ["## 可用工具", "你可以调用以下工具来完成任务："]
        for tool in self._tools:
            lines.append(tool.to_prompt_text())

        lines.append("\n**使用工具时**，输出 JSON 格式：")
        lines.append('```json')
        lines.append('{"tool": "工具名", "parameters": {...}}')
        lines.append('```')

        return "\n".join(lines)

    def clear(self) -> "PromptBuilder":
        """清空所有配置。"""
        self._parts.clear()
        self._context = None
        self._tools.clear()
        self._variables.clear()
        return self

    def clone(self) -> "PromptBuilder":
        """克隆当前 builder。"""
        new_builder = PromptBuilder()
        new_builder._parts = list(self._parts)
        new_builder._context = self._context
        new_builder._tools = list(self._tools)
        new_builder._variables = dict(self._variables)
        return new_builder

    def to_dict(self) -> dict[str, Any]:
        """导出配置（用于调试/持久化）。"""
        return {
            "parts": [p.to_dict() for p in self._parts],
            "context": self._context.to_dict() if self._context else None,
            "tools": [t.name for t in self._tools],
            "variables": self._variables,
        }


# ── 便捷函数 ──────────────────────────────────────────────────────────


def build_vimax_agent_prompt(
    session_id: str = "",
    project_name: str = "",
    previous_summary: str = "",
    tools: list[ToolInfo] | None = None,
) -> str:
    """构建 ViMax 风格的 agent prompt（便捷函数）。

    Args:
        session_id: 会话 ID
        project_name: 项目名称
        previous_summary: 之前对话摘要
        tools: 工具列表

    Returns:
        system prompt
    """
    builder = PromptBuilder()

    # 基础模板
    base_template = """# Hevi Video Generation Assistant

你是 Hevi，一个智能视频生成助手。你可以帮助用户：
- 从文字描述生成视频
- 从小说/文章生成长视频
- 上传照片生成客串角色
- 管理视频生成管线

## 工作原则

1. **理解需求**：仔细分析用户的请求，必要时询问澄清
2. **规划方案**：制定清晰的生成计划，包括场景、角色、镜头
3. **执行生成**：调用合适的工具生成视频
4. **质量保证**：检查生成结果，必要时重新生成
5. **透明沟通**：告知用户进度、成本和可能的限制
"""
    builder.add_template(base_template, "base", priority=100)

    # 上下文
    context = PromptContext(
        session_id=session_id,
        project_name=project_name,
        previous_summary=previous_summary,
    )
    builder.set_context(context)

    # 工具
    if tools:
        builder.add_tools(tools)

    return builder.build()


def build_pipeline_prompt(
    pipeline_type: str,
    context: PromptContext | None = None,
) -> str:
    """构建管线专用 prompt。

    Args:
        pipeline_type: 管线类型（idea2video / script2video / novel2video）
        context: 上下文

    Returns:
        system prompt
    """
    pipeline_descriptions = {
        "idea2video": "从简短想法生成完整视频",
        "script2video": "从剧本生成视频",
        "novel2video": "从长文本（小说/文章）生成视频",
    }

    description = pipeline_descriptions.get(pipeline_type, "视频生成")

    builder = PromptBuilder()
    template = f"""# {pipeline_type} Pipeline

你是 {pipeline_type} 管线助手，专注于{description}。

## 工作流程

1. 分析输入内容
2. 提取关键信息（角色、场景、情节）
3. 制定生成计划
4. 调用工具生成视频
5. 质量检查和优化
"""
    builder.add_template(template, "pipeline", priority=100)

    if context:
        builder.set_context(context)

    return builder.build()
