"""
ViMax Batch 2 测试套件
覆盖 Agent Runtime 四大模块:
  - Session Index (会话持久化)
  - Context Compactor (上下文压缩)
  - Pipeline Checkpoint (断点续跑)
  - Agent Loop (自主 Agent 循环)
"""
import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest


# ═══════════════════════════════════════════════════════════════════════
# Session Index 测试
# ═══════════════════════════════════════════════════════════════════════


class TestSessionIndex:
    """会话索引测试"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sessions_dir = Path(self.temp_dir) / "sessions"

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_session(self):
        from hevi.agent_runtime import SessionIndex

        index = SessionIndex(self.sessions_dir)
        session_id = index.create_session()

        assert session_id is not None
        assert len(session_id) > 0
        assert self.sessions_dir.exists()
        assert (self.sessions_dir / session_id).exists()

    def test_create_session_with_id(self):
        from hevi.agent_runtime import SessionIndex

        index = SessionIndex(self.sessions_dir)
        session_id = index.create_session("my-session-123")

        assert session_id == "my-session-123"

    def test_list_sessions(self):
        from hevi.agent_runtime import SessionIndex

        index = SessionIndex(self.sessions_dir)
        index.create_session("session-1")
        index.create_session("session-2")
        index.create_session("session-3")

        sessions = index.list_sessions()
        assert len(sessions) == 3

    def test_delete_session(self):
        from hevi.agent_runtime import SessionIndex

        index = SessionIndex(self.sessions_dir)
        session_id = index.create_session()

        assert (self.sessions_dir / session_id).exists()

        index.delete_session(session_id)
        assert not (self.sessions_dir / session_id).exists()

    def test_add_and_get_turn(self):
        from hevi.agent_runtime import SessionIndex, TurnRecord

        index = SessionIndex(self.sessions_dir)
        session_id = index.create_session()

        turn = TurnRecord(
            turn_id="turn-001",
            user_input="Hello",
            assistant_output="Hi there!",
            tool_calls=[{"name": "search", "args": {}}],
            tool_results=[{"name": "search", "output": "result"}],
        )

        index.add_turn(session_id, turn)

        turns = index.get_turns(session_id)
        assert len(turns) == 1
        assert turns[0].turn_id == "turn-001"
        assert turns[0].user_input == "Hello"

    def test_multiple_turns(self):
        from hevi.agent_runtime import SessionIndex, TurnRecord

        index = SessionIndex(self.sessions_dir)
        session_id = index.create_session()

        for i in range(5):
            turn = TurnRecord(
                turn_id=f"turn-{i:03d}",
                user_input=f"Question {i}",
                assistant_output=f"Answer {i}",
            )
            index.add_turn(session_id, turn)

        turns = index.get_turns(session_id)
        assert len(turns) == 5

    def test_add_and_get_compaction(self):
        from hevi.agent_runtime import SessionIndex, CompactionRecord

        index = SessionIndex(self.sessions_dir)
        session_id = index.create_session()

        compaction = CompactionRecord(
            compaction_id="comp-001",
            timestamp=time.time(),
            messages_before=50,
            messages_after=20,
            tokens_before=100000,
            tokens_after=40000,
            summary="This is a summary",
        )

        index.add_compaction(session_id, compaction)

        compactions = index.get_compactions(session_id)
        assert len(compactions) == 1
        assert compactions[0].compaction_id == "comp-001"

    def test_resume_session(self):
        from hevi.agent_runtime import SessionIndex, TurnRecord

        index = SessionIndex(self.sessions_dir)
        session_id = index.create_session()

        turn = TurnRecord(
            turn_id="turn-001",
            user_input="Test",
            assistant_output="Response",
        )
        index.add_turn(session_id, turn)

        resumed = index.resume_session(session_id)
        assert resumed is not None
        assert len(resumed["turns"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# Context Compactor 测试
# ═══════════════════════════════════════════════════════════════════════


class TestContextCompactor:
    """上下文压缩器测试"""

    def test_estimate_tokens(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor()

        messages = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        tokens = compactor.estimate_tokens(messages)
        assert tokens > 0

    def test_estimate_tokens_multimodal(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {"type": "image_url", "image_url": "data:image/png;base64,..."},
                ],
            }
        ]

        tokens = compactor.estimate_tokens(messages)
        assert tokens > 1000  # 图像至少 1000 tokens

    def test_should_compact_false(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor(token_threshold=100000)

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        assert not compactor.should_compact(messages)

    def test_should_compact_true(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor(token_threshold=10)

        messages = [
            {"role": "user", "content": "This is a very long message that should trigger compaction"},
            {"role": "assistant", "content": "And this is another long response"},
        ]

        assert compactor.should_compact(messages)

    @pytest.mark.asyncio
    async def test_compact_no_messages(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor()
        result = await compactor.compact([])

        assert result.messages_before == 0
        assert result.messages_after == 0

    @pytest.mark.asyncio
    async def test_compact_few_messages(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor(preserve_last_n=5)

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]

        result = await compactor.compact(messages)

        # 消息太少，不应该压缩
        assert result.summary == ""

    @pytest.mark.asyncio
    async def test_compact_many_messages(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor(preserve_last_n=3)

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "content": "A3"},
            {"role": "user", "content": "Q4"},
            {"role": "assistant", "content": "A4"},
        ]

        result = await compactor.compact(messages)

        # 应该生成摘要
        assert result.summary != ""
        assert result.messages_before > result.messages_after

    @pytest.mark.asyncio
    async def test_compact_with_tool_calls(self):
        from hevi.agent_runtime import ContextCompactor

        compactor = ContextCompactor(preserve_last_n=2)

        messages = [
            {"role": "user", "content": "Search for X"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "search", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "content": "Search result"},
            {"role": "assistant", "content": "Found it!"},
            {"role": "user", "content": "Thanks"},
            {"role": "assistant", "content": "Welcome"},
        ]

        result = await compactor.compact(messages)
        assert result.summary != ""

    @pytest.mark.asyncio
    async def test_compact_with_llm_caller(self):
        from hevi.agent_runtime import ContextCompactor

        async def mock_llm(prompt: str) -> str:
            return "## 关键任务\n- 用户请求帮助\n\n## 重要决策\n- 完成了任务"

        compactor = ContextCompactor(
            preserve_last_n=2,
            llm_caller=mock_llm,
        )

        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "content": "A3"},
        ]

        result = await compactor.compact(messages)
        assert "关键任务" in result.summary

    def test_save_compaction(self):
        from hevi.agent_runtime import ContextCompactor, CompactionResult

        compactor = ContextCompactor()

        result = CompactionResult(
            messages_before=50,
            messages_after=20,
            tokens_before=100000,
            tokens_after=40000,
            summary="Summary text",
            preserved_messages=[],
            timestamp=time.time(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "compaction.json"
            compactor.save_compaction(result, output_path)

            assert output_path.exists()
            with open(output_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                assert data["summary"] == "Summary text"


# ═══════════════════════════════════════════════════════════════════════
# Pipeline Checkpoint 测试
# ═══════════════════════════════════════════════════════════════════════


class TestPipelineCheckpoint:
    """管线检查点测试"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.working_dir = Path(self.temp_dir) / "working"

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_checkpoint(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        assert self.working_dir.exists()
        assert (self.working_dir / "artifacts").exists()

    def test_create_stage(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("extract_chars", version=1)

        assert stage.stage_name == "extract_chars"
        assert stage.artifact_dir.exists()

    def test_save_and_load(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        data = {"characters": ["Alice", "Bob"]}
        checkpoint.save(stage, "scene_01", data)

        loaded = checkpoint.load(stage, "scene_01")
        assert loaded == data

    def test_exists(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        assert not checkpoint.exists(stage, "scene_01")

        checkpoint.save(stage, "scene_01", {"data": "value"})
        assert checkpoint.exists(stage, "scene_01")

    def test_load_metadata(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        checkpoint.save(
            stage,
            "scene_01",
            {"data": "value"},
            inputs={"script": "hash"},
            duration_s=1.5,
        )

        metadata = checkpoint.load_metadata(stage, "scene_01")
        assert metadata is not None
        assert metadata.artifact_id == "scene_01"
        assert metadata.duration_s == 1.5
        assert metadata.input_hash != ""

    @pytest.mark.asyncio
    async def test_run_if_missing_executes(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        call_count = 0

        async def expensive_func():
            nonlocal call_count
            call_count += 1
            return {"result": "computed"}

        result = await checkpoint.run_if_missing(
            stage,
            "scene_01",
            expensive_func,
        )

        assert result == {"result": "computed"}
        assert call_count == 1

        # 第二次调用应该跳过
        result2 = await checkpoint.run_if_missing(
            stage,
            "scene_01",
            expensive_func,
        )

        assert result2 == {"result": "computed"}
        assert call_count == 1  # 没有再次执行

    @pytest.mark.asyncio
    async def test_run_if_missing_force(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        call_count = 0

        async def expensive_func():
            nonlocal call_count
            call_count += 1
            return {"result": call_count}

        await checkpoint.run_if_missing(stage, "scene_01", expensive_func)
        assert call_count == 1

        # 强制执行
        result = await checkpoint.run_if_missing(
            stage,
            "scene_01",
            expensive_func,
            force=True,
        )

        assert result == {"result": 2}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_run_if_missing_input_change(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        call_count = 0

        async def expensive_func():
            nonlocal call_count
            call_count += 1
            return {"result": call_count}

        await checkpoint.run_if_missing(
            stage,
            "scene_01",
            expensive_func,
            inputs={"script": "v1"},
        )
        assert call_count == 1

        # 输入改变，应该重新执行
        result = await checkpoint.run_if_missing(
            stage,
            "scene_01",
            expensive_func,
            inputs={"script": "v2"},
        )

        assert result == {"result": 2}
        assert call_count == 2

    def test_list_artifacts(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        checkpoint.save(stage, "scene_01", {"data": 1})
        checkpoint.save(stage, "scene_02", {"data": 2})
        checkpoint.save(stage, "scene_03", {"data": 3})

        artifacts = checkpoint.list_artifacts(stage)
        assert len(artifacts) == 3

    def test_delete_artifact(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)
        stage = checkpoint.stage("test_stage")

        checkpoint.save(stage, "scene_01", {"data": 1})
        assert checkpoint.exists(stage, "scene_01")

        checkpoint.delete_artifact(stage, "scene_01")
        assert not checkpoint.exists(stage, "scene_01")

    def test_get_stats(self):
        from hevi.agent_runtime import PipelineCheckpoint

        checkpoint = PipelineCheckpoint(self.working_dir)

        stage1 = checkpoint.stage("stage1")
        checkpoint.save(stage1, "item1", {"data": "a" * 1000})
        checkpoint.save(stage1, "item2", {"data": "b" * 1000})

        stage2 = checkpoint.stage("stage2")
        checkpoint.save(stage2, "item1", {"data": "c" * 1000})

        stats = checkpoint.get_stats()
        assert stats["total_artifacts"] == 3
        assert "stage1" in stats["stages"]
        assert "stage2" in stats["stages"]

    @pytest.mark.asyncio
    async def test_checkpointed_pipeline(self):
        from hevi.agent_runtime import CheckpointedPipeline

        class MyPipeline(CheckpointedPipeline):
            def stages(self) -> List[str]:
                return ["extract", "analyze", "generate"]

            async def run_stage(
                self,
                stage_name: str,
                artifact_id: str,
                **kwargs,
            ) -> Any:
                if stage_name == "extract":
                    return {"chars": ["Alice", "Bob"]}
                elif stage_name == "analyze":
                    chars = kwargs.get("previous", {}).get("extract", {}).get("chars", [])
                    return {"count": len(chars)}
                elif stage_name == "generate":
                    count = kwargs.get("previous", {}).get("analyze", {}).get("count", 0)
                    return {"output": f"Generated {count} items"}
                return {}

        pipeline = MyPipeline(self.working_dir)
        results = await pipeline.run("test_artifact")

        assert "extract" in results
        assert "analyze" in results
        assert "generate" in results
        assert results["extract"]["chars"] == ["Alice", "Bob"]


# ═══════════════════════════════════════════════════════════════════════
# Agent Loop 测试
# ═══════════════════════════════════════════════════════════════════════


class TestAgentLoop:
    """Agent Loop 测试"""

    @pytest.mark.asyncio
    async def test_simple_conversation(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry

        async def mock_llm_caller(messages, tools):
            # 模拟 LLM：如果没有工具调用就结束
            last_msg = messages[-1]
            if last_msg["role"] == "user":
                return "Hello! How can I help you?", []
            return "Done!", []

        registry = ToolRegistry()
        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
        )

        events = []
        async for event in loop.run("Hi there"):
            events.append(event)

        assert len(events) >= 2  # turn + done
        assert events[0].type == "turn"
        assert events[-1].type == "done"
        assert "Hello" in events[-1].data["assistant"]

    @pytest.mark.asyncio
    async def test_tool_calling(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry, ToolCall

        call_count = 0

        async def mock_llm_caller(messages, tools):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # 第一次：调用工具
                return "", [
                    ToolCall(
                        id="call_1",
                        name="search",
                        arguments={"query": "test"},
                    )
                ]
            else:
                # 第二次：结束
                return "Found the answer!", []

        async def search_tool(query: str, **kwargs):
            return f"Results for: {query}"

        registry = ToolRegistry()
        registry.register(
            name="search",
            fn=search_tool,
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
            },
        )

        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
        )

        events = []
        async for event in loop.run("Search for test"):
            events.append(event)

        # 应该有 tool_start 和 tool_result 事件
        event_types = [e.type for e in events]
        assert "tool_start" in event_types
        assert "tool_result" in event_types
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry, ToolCall

        call_count = 0

        async def mock_llm_caller(messages, tools):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # 调用多个工具
                return "", [
                    ToolCall(id="call_1", name="tool1", arguments={}),
                    ToolCall(id="call_2", name="tool2", arguments={}),
                ]
            else:
                return "All done!", []

        async def tool1(**kwargs):
            return "result1"

        async def tool2(**kwargs):
            return "result2"

        registry = ToolRegistry()
        registry.register("tool1", tool1, "Tool 1", {"type": "object", "properties": {}})
        registry.register("tool2", tool2, "Tool 2", {"type": "object", "properties": {}})

        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
        )

        events = []
        async for event in loop.run("Use both tools"):
            events.append(event)

        tool_starts = [e for e in events if e.type == "tool_start"]
        assert len(tool_starts) == 2

    @pytest.mark.asyncio
    async def test_max_tool_passes(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry, ToolCall

        async def mock_llm_caller(messages, tools):
            # 总是调用工具，永不停止
            return "", [ToolCall(id=f"call_{len(messages)}", name="loop", arguments={})]

        async def loop_tool(**kwargs):
            return "looping"

        registry = ToolRegistry()
        registry.register("loop", loop_tool, "Loop tool", {"type": "object", "properties": {}})

        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
            max_tool_passes=5,
        )

        events = []
        async for event in loop.run("Loop forever"):
            events.append(event)

        # 应该以 error 结束
        assert events[-1].type == "error"
        assert "超过" in events[-1].data["message"] or "exceeded" in events[-1].data["message"].lower()

    @pytest.mark.asyncio
    async def test_run_once(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry

        async def mock_llm_caller(messages, tools):
            return "Simple response", []

        registry = ToolRegistry()
        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
        )

        result = await loop.run_once("Test")
        assert result == "Simple response"

    @pytest.mark.asyncio
    async def test_llm_error(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry

        async def mock_llm_caller(messages, tools):
            raise RuntimeError("LLM failed")

        registry = ToolRegistry()
        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
        )

        events = []
        async for event in loop.run("Test"):
            events.append(event)

        assert events[-1].type == "error"
        assert "LLM" in events[-1].data["message"]

    @pytest.mark.asyncio
    async def test_tool_error(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry, ToolCall

        call_count = 0

        async def mock_llm_caller(messages, tools):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                return "", [ToolCall(id="call_1", name="failing_tool", arguments={})]
            else:
                return "Recovered", []

        async def failing_tool(**kwargs):
            raise ValueError("Tool failed!")

        registry = ToolRegistry()
        registry.register(
            "failing_tool",
            failing_tool,
            "A failing tool",
            {"type": "object", "properties": {}},
        )

        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
        )

        events = []
        async for event in loop.run("Test"):
            events.append(event)

        # 应该有 tool_result 事件，ok=False
        tool_results = [e for e in events if e.type == "tool_result"]
        assert len(tool_results) == 1
        assert not tool_results[0].data["ok"]

        # 循环应该继续并最终完成
        assert events[-1].type == "done"

    def test_reset(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry

        async def mock_llm_caller(messages, tools):
            return "Response", []

        registry = ToolRegistry()
        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
        )

        # 模拟添加消息
        loop._messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "test"},
        ]

        assert loop.message_count == 2

        loop.reset()
        assert loop.message_count == 0

    @pytest.mark.asyncio
    async def test_with_session_index(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry, SessionIndex

        async def mock_llm_caller(messages, tools):
            return "Response with session", []

        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            session_index = SessionIndex(sessions_dir)
            session_id = session_index.create_session()

            registry = ToolRegistry()
            loop = AgentLoop(
                llm_caller=mock_llm_caller,
                tool_registry=registry,
                session_index=session_index,
                session_id=session_id,
            )

            events = []
            async for event in loop.run("Test with session"):
                events.append(event)

            # 应该保存 turn
            turns = session_index.get_turns(session_id)
            assert len(turns) == 1

    @pytest.mark.asyncio
    async def test_with_compactor(self):
        from hevi.agent_runtime import AgentLoop, ToolRegistry, ContextCompactor

        async def mock_llm_caller(messages, tools):
            return "Response after compaction", []

        # 设置低阈值触发压缩
        compactor = ContextCompactor(token_threshold=10, preserve_last_n=2)

        registry = ToolRegistry()
        loop = AgentLoop(
            llm_caller=mock_llm_caller,
            tool_registry=registry,
            compactor=compactor,
        )

        # 添加很多消息触发压缩
        loop._messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "This is a very long message that will trigger compaction"},
            {"role": "assistant", "content": "This is a very long response that will also trigger compaction"},
            {"role": "user", "content": "Another long message here"},
            {"role": "assistant", "content": "Another long response here"},
        ]

        events = []
        async for event in loop.run("Test compaction"):
            events.append(event)

        # 应该有 compacting 状态事件
        status_events = [e for e in events if e.type == "status"]
        compacting = [e for e in status_events if e.data.get("phase") == "compacting"]
        assert len(compacting) > 0


# ═══════════════════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════════════════


class TestAgentRuntimeIntegration:
    """Agent Runtime 集成测试"""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """完整工作流：创建会话 → Agent Loop → 工具调用 → 压缩 → 恢复"""
        from hevi.agent_runtime import (
            AgentLoop,
            ToolRegistry,
            SessionIndex,
            ContextCompactor,
            PipelineCheckpoint,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            sessions_dir = tmpdir / "sessions"
            working_dir = tmpdir / "working"

            # 创建会话
            session_index = SessionIndex(sessions_dir)
            session_id = session_index.create_session()

            # 创建检查点
            checkpoint = PipelineCheckpoint(working_dir)

            # 创建压缩器
            compactor = ContextCompactor(token_threshold=50, preserve_last_n=3)

            # 注册工具
            async def save_data(key: str, value: str, **kwargs):
                stage = checkpoint.stage("save_data")
                checkpoint.save(stage, key, {"value": value})
                return f"Saved {key}={value}"

            registry = ToolRegistry()
            registry.register(
                "save_data",
                save_data,
                "Save data to checkpoint",
                {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                },
            )

            # 模拟 LLM
            call_count = 0

            async def mock_llm(messages, tools):
                nonlocal call_count
                call_count += 1

                if call_count == 1:
                    # 调用保存工具
                    return "", [
                        __import__("hevi.agent_runtime.loop", fromlist=["ToolCall"]).ToolCall(
                            id="call_1",
                            name="save_data",
                            arguments={"key": "test", "value": "hello"},
                        )
                    ]
                else:
                    return "Data saved successfully!", []

            # 创建 Agent Loop
            loop = AgentLoop(
                llm_caller=mock_llm,
                tool_registry=registry,
                session_index=session_index,
                session_id=session_id,
                compactor=compactor,
            )

            # 运行
            events = []
            async for event in loop.run("Save some data"):
                events.append(event)

            # 验证
            assert events[-1].type == "done"

            # 验证检查点
            stage = checkpoint.stage("save_data")
            assert checkpoint.exists(stage, "test")
            data = checkpoint.load(stage, "test")
            assert data["value"] == "hello"

            # 验证会话
            turns = session_index.get_turns(session_id)
            assert len(turns) == 1

    def test_import_all(self):
        """测试所有导入"""
        from hevi.agent_runtime import (
            AgentEvent,
            AgentLoop,
            ToolCall,
            ToolDefinition,
            ToolRegistry,
            ToolResult,
            CompactionResult,
            ContextCompactor,
            CompactionRecord,
            SessionIndex,
            SessionMetadata,
            TurnRecord,
            ArtifactMetadata,
            CheckpointedPipeline,
            PipelineCheckpoint,
            StageConfig,
        )

        # 确保所有类都可以实例化或访问
        assert AgentEvent is not None
        assert ToolRegistry is not None
        assert ContextCompactor is not None
        assert SessionIndex is not None
        assert PipelineCheckpoint is not None
