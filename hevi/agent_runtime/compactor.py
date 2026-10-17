"""
上下文压缩器（对标 ViMax context_compactor.py）

当对话历史过长时自动压缩，保留关键信息，释放 token 预算：
- 估算消息 token 数（启发式）
- 阈值触发压缩
- 保留最近 N 条消息
- LLM 生成结构化摘要
- 支持多种摘要格式
"""
import re
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable, Awaitable
from pathlib import Path


@dataclass
class CompactionResult:
    """压缩结果"""
    messages_before: int
    messages_after: int
    tokens_before: int
    tokens_after: int
    summary: str
    preserved_messages: List[Dict[str, Any]]
    timestamp: float


class ContextCompactor:
    """
    上下文压缩器

    压缩策略:
    1. 保留 system prompt（第一条）
    2. 保留最近 preserve_last_n 条消息
    3. 中间部分用 LLM 生成摘要替换
    4. 摘要格式结构化（按角色分段）
    """

    def __init__(
        self,
        token_threshold: int = 100_000,
        preserve_last_n: int = 10,
        llm_caller: Optional[Callable[[str], Awaitable[str]]] = None,
        summary_format: str = "structured",  # structured | bullet | narrative
    ):
        self.token_threshold = token_threshold
        self.preserve_last_n = preserve_last_n
        self.llm_caller = llm_caller
        self.summary_format = summary_format

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """估算消息 token 数（启发式）"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                # 粗略估算: 1 token ≈ 4 chars (英文) or 1.5 chars (中文)
                # 混合估算: 1 token ≈ 3 chars
                total += len(content) // 3
            elif isinstance(content, list):
                # 多模态消息
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            total += len(item.get("text", "")) // 3
                        elif item.get("type") == "image_url":
                            total += 1000  # 图像约 1000 tokens
        return total

    def should_compact(self, messages: List[Dict[str, Any]]) -> bool:
        """判断是否需要压缩"""
        tokens = self.estimate_tokens(messages)
        return tokens > self.token_threshold

    async def compact(
        self,
        messages: List[Dict[str, Any]],
        extra_context: Optional[str] = None,
    ) -> CompactionResult:
        """
        执行压缩

        Args:
            messages: 完整对话历史
            extra_context: 额外上下文信息

        Returns:
            CompactionResult
        """
        if not messages:
            return CompactionResult(
                messages_before=0,
                messages_after=0,
                tokens_before=0,
                tokens_after=0,
                summary="",
                preserved_messages=[],
                timestamp=time.time(),
            )

        tokens_before = self.estimate_tokens(messages)
        messages_before = len(messages)

        # 分离消息
        system_msg = None
        if messages and messages[0].get("role") == "system":
            system_msg = messages[0]
            rest = messages[1:]
        else:
            rest = messages

        # 保留最近 N 条
        if len(rest) > self.preserve_last_n:
            to_summarize = rest[:-self.preserve_last_n]
            preserved = rest[-self.preserve_last_n:]
        else:
            to_summarize = []
            preserved = rest

        # 生成摘要
        if to_summarize:
            summary = await self._generate_summary(to_summarize, extra_context)
        else:
            summary = ""

        # 重组消息
        new_messages = []
        if system_msg:
            new_messages.append(system_msg)

        # 添加摘要作为 system 消息
        if summary:
            summary_msg = {
                "role": "system",
                "content": f"[上下文摘要]\n{summary}",
            }
            new_messages.append(summary_msg)

        # 添加保留的消息
        new_messages.extend(preserved)

        tokens_after = self.estimate_tokens(new_messages)
        messages_after = len(new_messages)

        return CompactionResult(
            messages_before=messages_before,
            messages_after=messages_after,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            summary=summary,
            preserved_messages=preserved,
            timestamp=time.time(),
        )

    async def _generate_summary(
        self,
        messages: List[Dict[str, Any]],
        extra_context: Optional[str],
    ) -> str:
        """生成对话摘要"""
        # 构建摘要提示
        conversation_text = self._format_messages_for_summary(messages)

        if self.summary_format == "structured":
            prompt = self._build_structured_summary_prompt(conversation_text, extra_context)
        elif self.summary_format == "bullet":
            prompt = self._build_bullet_summary_prompt(conversation_text, extra_context)
        else:
            prompt = self._build_narrative_summary_prompt(conversation_text, extra_context)

        # 调用 LLM 生成摘要
        if self.llm_caller:
            try:
                summary = await self.llm_caller(prompt)
                return summary
            except Exception as e:
                # LLM 失败，回退到规则摘要
                return self._rule_based_summary(messages)
        else:
            # 无 LLM，使用规则摘要
            return self._rule_based_summary(messages)

    def _format_messages_for_summary(self, messages: List[Dict[str, Any]]) -> str:
        """格式化消息为文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, str):
                lines.append(f"[{role.upper()}]\n{content}")
            elif isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                if text_parts:
                    lines.append(f"[{role.upper()}]\n{' '.join(text_parts)}")

            # 添加工具调用
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    lines.append(f"[TOOL CALL] {func.get('name', 'unknown')}")

        return "\n\n".join(lines)

    def _build_structured_summary_prompt(
        self,
        conversation: str,
        extra_context: Optional[str],
    ) -> str:
        """构建结构化摘要提示"""
        prompt = f"""请为以下对话生成结构化摘要，用于压缩上下文。

要求：
1. 识别对话中的关键任务和决策
2. 提取重要的文件路径和代码变更
3. 记录未解决的问题和下一步计划
4. 保持简洁，突出关键信息

输出格式：
## 关键任务
- ...

## 重要决策
- ...

## 文件变更
- ...

## 未解决问题
- ...

## 下一步
- ...

对话内容：
{conversation}
"""
        if extra_context:
            prompt += f"\n额外上下文：\n{extra_context}"

        return prompt

    def _build_bullet_summary_prompt(
        self,
        conversation: str,
        extra_context: Optional[str],
    ) -> str:
        """构建要点摘要提示"""
        prompt = f"""请用要点形式总结以下对话的关键内容：

对话内容：
{conversation}

输出要点列表，每条不超过 2 行。
"""
        if extra_context:
            prompt += f"\n额外上下文：\n{extra_context}"

        return prompt

    def _build_narrative_summary_prompt(
        self,
        conversation: str,
        extra_context: Optional[str],
    ) -> str:
        """构建叙述摘要提示"""
        prompt = f"""请用 2-3 段话叙述以下对话的主要内容：

对话内容：
{conversation}

重点描述：做了什么、为什么做、结果如何。
"""
        if extra_context:
            prompt += f"\n额外上下文：\n{extra_context}"

        return prompt

    def _rule_based_summary(self, messages: List[Dict[str, Any]]) -> str:
        """规则摘要（无 LLM 回退）"""
        lines = ["## 对话摘要（规则生成）"]

        # 统计
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
        tool_msgs = [m for m in messages if m.get("role") == "tool"]

        lines.append(f"- 用户消息: {len(user_msgs)} 条")
        lines.append(f"- 助手消息: {len(assistant_msgs)} 条")
        lines.append(f"- 工具调用: {len(tool_msgs)} 条")

        # 提取工具名称
        tool_names = set()
        for msg in messages:
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                name = func.get("name", "")
                if name:
                    tool_names.add(name)

        if tool_names:
            lines.append(f"- 使用的工具: {', '.join(sorted(tool_names))}")

        # 提取最近的助手消息片段
        if assistant_msgs:
            last_assistant = assistant_msgs[-1]
            content = last_assistant.get("content", "")
            if isinstance(content, str) and content:
                snippet = content[:200] + "..." if len(content) > 200 else content
                lines.append(f"- 最近助手回复片段: {snippet}")

        return "\n".join(lines)

    def save_compaction(self, result: CompactionResult, output_path: Path) -> None:
        """保存压缩结果到文件"""
        import json
        output_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "messages_before": result.messages_before,
            "messages_after": result.messages_after,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "summary": result.summary,
            "timestamp": result.timestamp,
            "preserved_count": len(result.preserved_messages),
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
