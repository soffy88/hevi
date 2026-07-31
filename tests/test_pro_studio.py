"""Pro Studio 5 模块测试 — IndexTTS2/素材搜索/直播/多Agent/代码解说。

Run: .venv/bin/python -m pytest tests/test_pro_studio.py --noconftest -q
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest


# ===================================================================
# 1. IndexTTS2 情感语音
# ===================================================================

class TestIndexTTS:

    def test_emotion_vector(self):
        from hevi.audio.indextts_service import EmotionVector
        v = EmotionVector(happy=0.8, sad=0.2)
        assert v.happy == 0.8
        assert v.to_list()[0] == 0.8
        assert len(v.to_list()) == 8

    def test_emotion_from_text(self):
        from hevi.audio.indextts_service import emotion_from_text
        # Happy text
        v = emotion_from_text("今天太开心了！哈哈")
        assert v.happy > 0.0
        # Sad text
        v = emotion_from_text("好难过啊，cry")
        assert v.sad > 0.0
        # Angry
        v = emotion_from_text("太生气了！angry!")
        assert v.angry > 0.0

    def test_supported_emotions(self):
        from hevi.audio.indextts_service import supported_emotions
        emotions = supported_emotions()
        assert len(emotions) == 8
        assert "happy" in emotions
        assert "calm" in emotions

    def test_emotion_from_list(self):
        from hevi.audio.indextts_service import EmotionVector
        v = EmotionVector.from_list([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
        assert v.happy == 0.1
        assert v.calm == 0.8

    @pytest.mark.asyncio
    async def test_synthesize_missing_speaker(self):
        from hevi.audio.indextts_service import IndexTTSRequest, synthesize_indextts
        req = IndexTTSRequest(text="test", speaker_audio_path="/nonexistent.wav")
        result = await synthesize_indextts(req)
        assert not result.success

    @pytest.mark.asyncio
    async def test_synthesize_success(self):
        import tempfile
        from hevi.audio.indextts_service import IndexTTSRequest, EmotionVector, synthesize_indextts
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF" + b"\x00" * 100)
            speaker_path = f.name

        req = IndexTTSRequest(
            text="这是一段测试文本",
            speaker_audio_path=speaker_path,
            emotion_vector=EmotionVector(happy=0.8, sad=0.2),
            target_duration_sec=3.0,
            output_path=f"/tmp/indextts_{id(f)}.wav",
        )
        result = await synthesize_indextts(req)
        assert result.success
        assert result.emotion_applied
        assert result.duration_controlled


# ===================================================================
# 2. 素材搜索
# ===================================================================

class TestStockSearch:

    def test_stock_request_model(self):
        from hevi.image.stock_footage import StockSearchRequest, StockMediaType, StockProvider
        req = StockSearchRequest(
            query="sunset",
            media_type=StockMediaType.video,
            provider=StockProvider.pexels,
            count=5,
        )
        assert req.query == "sunset"
        assert req.provider == StockProvider.pexels

    def test_stock_item_model(self):
        from hevi.image.stock_footage import StockItem
        item = StockItem(
            id="123",
            url="https://example.com/video.mp4",
            preview_url="https://example.com/thumb.jpg",
            width=1920,
            height=1080,
            duration=30.0,
            provider="pexels",
            media_type="video",
        )
        assert item.id == "123"
        assert item.duration == 30.0

    @pytest.mark.asyncio
    async def test_search_stock_missing_key_pexels(self):
        import os
        old = os.environ.pop("PEXELS_API_KEY", None)
        try:
            from hevi.image.stock_footage import StockSearchRequest, StockProvider, search_stock
            req = StockSearchRequest(query="test", provider=StockProvider.pexels)
            result = await search_stock(req)
            assert not result.success
            assert "not set" in (result.error or "")
        finally:
            if old:
                os.environ["PEXELS_API_KEY"] = old

    @pytest.mark.asyncio
    async def test_search_stock_missing_key_pixabay(self):
        import os
        old = os.environ.pop("PIXABAY_API_KEY", None)
        try:
            from hevi.image.stock_footage import StockSearchRequest, StockProvider, search_stock
            req = StockSearchRequest(query="test", provider=StockProvider.pixabay)
            result = await search_stock(req)
            assert not result.success
        finally:
            if old:
                os.environ["PIXABAY_API_KEY"] = old


# ===================================================================
# 3. 数字人直播
# ===================================================================

class TestLiveStream:

    @pytest.mark.asyncio
    async def test_start_missing_rtmp(self):
        from hevi.livestream import (
            LiveStreamConfig, LiveStreamPlatform, LiveStreamRequest,
            LiveStreamState, start_livestream,
        )
        config = LiveStreamConfig(
            platform=LiveStreamPlatform.douyin,
            rtmp_url="", stream_key="",
            portrait_path="/tmp/test.png",
        )
        req = LiveStreamRequest(config=config)
        status = await start_livestream(req)
        assert status.state == LiveStreamState.error

    @pytest.mark.asyncio
    async def test_start_missing_portrait(self):
        from hevi.livestream import (
            LiveStreamConfig, LiveStreamPlatform, LiveStreamRequest,
            LiveStreamState, start_livestream,
        )
        config = LiveStreamConfig(
            platform=LiveStreamPlatform.douyin,
            rtmp_url="rtmp://test",
            stream_key="key",
            portrait_path="",
        )
        req = LiveStreamRequest(config=config)
        status = await start_livestream(req)
        assert status.state == LiveStreamState.error

    @pytest.mark.asyncio
    async def test_start_success(self):
        from hevi.livestream import (
            LiveStreamConfig, LiveStreamPlatform, LiveStreamRequest,
            LiveStreamState, start_livestream,
        )
        config = LiveStreamConfig(
            platform=LiveStreamPlatform.douyin,
            rtmp_url="rtmp://test/live",
            stream_key="stream_key_123",
            portrait_path="/tmp/portrait.png",
            title="测试直播",
        )
        req = LiveStreamRequest(config=config, script="话术脚本")
        status = await start_livestream(req)
        assert status.state == LiveStreamState.live
        assert status.platform == "douyin"

    @pytest.mark.asyncio
    async def test_stop_livestream(self):
        from hevi.livestream import (
            start_livestream, stop_livestream, get_livestream_status,
            LiveStreamConfig, LiveStreamPlatform, LiveStreamRequest,
            LiveStreamState,
        )
        config = LiveStreamConfig(
            platform=LiveStreamPlatform.bilibili,
            rtmp_url="rtmp://test/live",
            stream_key="key",
            portrait_path="/tmp/p.png",
        )
        req = LiveStreamRequest(config=config)
        started = await start_livestream(req)
        assert started.state == LiveStreamState.live

        stopped = await stop_livestream(started.id)
        assert stopped is not None
        assert stopped.state == LiveStreamState.idle

    def test_add_product(self):
        from hevi.livestream import (
            ProductItem, add_product, list_products,
        )
        product = ProductItem(
            name="测试产品",
            price="¥99",
            description="产品介绍",
            script="产品话术",
            keywords=["测试", "产品"],
        )
        result = add_product(product)
        assert result.name == "测试产品"
        products = list_products()
        assert len(products) >= 1

    @pytest.mark.asyncio
    async def test_list_active_streams(self):
        from hevi.livestream import (
            start_livestream, list_active_streams,
            LiveStreamConfig, LiveStreamPlatform, LiveStreamRequest,
        )
        config = LiveStreamConfig(
            platform=LiveStreamPlatform.youtube,
            rtmp_url="rtmp://a/live",
            stream_key="k",
            portrait_path="/tmp/p.png",
        )
        await start_livestream(LiveStreamRequest(config=config))
        active = list_active_streams()
        assert len(active) >= 1

    def test_scheduler(self):
        from datetime import datetime, timedelta
        from hevi.livestream import LiveStreamSchedule, StreamScheduler

        scheduler = StreamScheduler()
        schedule = LiveStreamSchedule(
            stream_request_id="test_stream",
            start_at=datetime.utcnow() + timedelta(hours=1),
            title="定时直播",
        )
        sid = scheduler.add_schedule(schedule)
        assert scheduler.get_schedules()[0].id == sid
        assert scheduler.remove_schedule(sid)


# ===================================================================
# 4. 多 Agent 编排
# ===================================================================

class TestAgentOrchestration:

    def test_create_video_plan(self):
        from hevi.agent.orchestration import create_video_plan
        plan = create_video_plan("这是一段视频脚本", "cinematic")
        assert len(plan.tasks) == 4  # script, voice, video, edit
        assert plan.dependencies
        assert "video_production" in plan.name

    def test_create_plan_with_publish(self):
        from hevi.agent.orchestration import create_video_plan
        plan = create_video_plan("脚本", platforms=["douyin", "bilibili"])
        assert len(plan.tasks) == 5  # + publish

    def test_agent_roles(self):
        from hevi.agent.orchestration import AgentRole
        roles = list(AgentRole)
        assert len(roles) == 7
        assert AgentRole.planner.value == "planner"
        assert AgentRole.publisher.value == "publisher"

    def test_emotion_vector_model(self):
        from hevi.agent.orchestration import AgentState
        assert AgentState.completed.value == "completed"

    def test_tool_call_model(self):
        from hevi.agent.orchestration import ToolCall, ToolResult
        call = ToolCall(tool_name="tts_synthesize", arguments={"text": "hello"})
        assert call.tool_name == "tts_synthesize"
        result = ToolResult(tool_call_id=call.id, output="audio.wav")
        assert result.success
        assert result.output == "audio.wav"

    def test_agent_plan_model(self):
        from hevi.agent.orchestration import AgentPlan, AgentTask, AgentStep, AgentRole, ToolCall
        plan = AgentPlan(
            name="test",
            tasks=[
                AgentTask(
                    steps=[
                        AgentStep(role=AgentRole.script_writer, tool_calls=[ToolCall(tool_name="llm", arguments={})])
                    ]
                )
            ],
        )
        assert len(plan.tasks) == 1
        assert plan.tasks[0].steps[0].role == AgentRole.script_writer


# ===================================================================
# 5. 代码解说视频
# ===================================================================

class TestCodeExplainer:

    def test_highlight_code(self):
        from hevi.assembly.code_explainer import _highlight_code
        code = "def hello():\n    print('Hi')\n"
        html = _highlight_code(code, "python")
        assert len(html) > 0
        assert '<pre' in html or '<span' in html

    def test_highlight_unknown_lang(self):
        from hevi.assembly.code_explainer import _highlight_code
        html = _highlight_code("some code", "unknown_lang_xyz")
        assert '<pre' in html

    def test_code_block_model(self):
        from hevi.assembly.code_explainer import CodeBlock
        block = CodeBlock(code="print(1)", language="python", narration="打印1", highlight_lines=[1])
        assert block.language == "python"
        assert 1 in block.highlight_lines

    def test_code_explainer_request(self):
        from hevi.assembly.code_explainer import CodeExplainerRequest, CodeBlock
        req = CodeExplainerRequest(
            blocks=[CodeBlock(code="x=1", language="python")],
            title="测试",
        )
        assert len(req.blocks) == 1

    @pytest.mark.asyncio
    async def test_generate_code_explainer(self):
        import random
        from hevi.assembly.code_explainer import (
            CodeBlock, CodeExplainerRequest, generate_code_explainer,
        )
        req = CodeExplainerRequest(
            blocks=[
                CodeBlock(code="def hello():\n    print('Hello World!')", language="python", narration="这是一个函数"),
                CodeBlock(code="if __name__=='__main__':\n    hello()", language="python", narration="运行入口"),
            ],
            title="Python 基础",
            output_path=f"/tmp/code_explainer_{random.randint(1000,9999)}.mp4",
        )
        result = await generate_code_explainer(req)
        assert result.success
        assert result.blocks_rendered == 2
        assert result.duration > 0


# ===================================================================
# 6. 模块导出
# ===================================================================

class TestExports:

    def test_indextts_exports(self):
        from hevi.audio.indextts_service import (
            IndexTTSRequest, IndexTTSResult, EmotionVector,
            synthesize_indextts, supported_emotions, emotion_from_text,
        )
        assert supported_emotions is not None

    def test_stock_exports(self):
        from hevi.image.stock_footage import (
            StockProvider, StockSearchRequest, search_stock,
            search_and_download, script_to_stock_clips,
        )
        assert search_stock is not None

    def test_livestream_exports(self):
        from hevi.livestream import (
            start_livestream, stop_livestream, list_active_streams,
            add_product, list_products, LiveStreamConfig,
        )
        assert start_livestream is not None

    def test_agent_exports(self):
        from hevi.agent.orchestration import (
            AgentRole, create_video_plan, AgentOrchestrator,
        )
        assert create_video_plan is not None

    def test_code_explainer_exports(self):
        from hevi.assembly.code_explainer import (
            CodeBlock, generate_code_explainer, _highlight_code,
        )
        assert generate_code_explainer is not None
