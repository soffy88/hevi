"""ViMax Batch 4 能力接入测试。

覆盖：
  - Novel2Video Pipeline（长文本→视频）
  - AutoCameo（参考照片→角色入戏）
  - Provider Presets（预置 provider 配置）
  - Prompt Builder（统一 prompt 构建系统）
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest


# ═══════════════════════════════════════════════════════════════════════
# Novel2Video Pipeline 测试
# ═══════════════════════════════════════════════════════════════════════


class TestNovel2VideoPipeline:
    """Novel2Video Pipeline 测试套件。"""

    def test_narrative_beat_creation(self):
        """测试 NarrativeBeat 创建。"""
        from hevi.director.novel2video import NarrativeBeat

        beat = NarrativeBeat(
            beat_id=1,
            title="相遇",
            description="小明在咖啡馆遇到小红",
            characters=["小明", "小红"],
            location="咖啡馆",
            emotion="惊喜",
            duration_s=5.0,
        )
        assert beat.beat_id == 1
        assert beat.title == "相遇"
        assert len(beat.characters) == 2
        assert beat.duration_s == 5.0

    def test_narrative_beat_to_dict(self):
        """测试 NarrativeBeat 序列化。"""
        from hevi.director.novel2video import NarrativeBeat

        beat = NarrativeBeat(
            beat_id=1,
            title="争吵",
            description="两人发生争执",
            characters=["小明", "小红"],
            location="街道",
            emotion="愤怒",
        )
        d = beat.to_dict()
        assert d["beat_id"] == 1
        assert d["title"] == "争吵"
        assert d["emotion"] == "愤怒"

    def test_event_creation(self):
        """测试 Event 创建。"""
        from hevi.director.novel2video import Event, NarrativeBeat

        beats = [
            NarrativeBeat(1, "开始", "故事开始"),
            NarrativeBeat(2, "发展", "故事发展"),
        ]
        event = Event(
            event_id=1,
            description="两人相遇并成为朋友",
            characters=["小明", "小红"],
            location="城市",
            time="第一天",
            beats=beats,
        )
        assert event.event_id == 1
        assert len(event.beats) == 2
        assert event.time == "第一天"

    def test_event_to_dict(self):
        """测试 Event 序列化。"""
        from hevi.director.novel2video import Event

        event = Event(
            event_id=1,
            description="关键事件",
            characters=["角色A"],
            location="地点X",
        )
        d = event.to_dict()
        assert d["event_id"] == 1
        assert d["description"] == "关键事件"
        assert "角色A" in d["characters"]

    def test_chapter_creation(self):
        """测试 Chapter 创建。"""
        from hevi.director.novel2video import Chapter

        chapter = Chapter(
            chapter_id=1,
            title="第一章",
            content="这是第一章的内容..." * 100,
        )
        assert chapter.chapter_id == 1
        assert chapter.title == "第一章"
        assert chapter.word_count > 0

    def test_chapter_word_count(self):
        """测试 Chapter 自动计算字数。"""
        from hevi.director.novel2video import Chapter

        content = "测试内容" * 50
        chapter = Chapter(1, "测试", content)
        assert chapter.word_count == len(content)

    def test_novel2video_config(self):
        """测试 Novel2VideoConfig 创建。"""
        from hevi.director.novel2video import Novel2VideoConfig

        config = Novel2VideoConfig(
            max_beats_per_chapter=10,
            max_events=25,
            max_scenes=40,
            target_duration_s=180.0,
        )
        assert config.max_beats_per_chapter == 10
        assert config.max_events == 25
        assert config.target_duration_s == 180.0

    def test_novel2video_config_to_dict(self):
        """测试 Novel2VideoConfig 序列化。"""
        from hevi.director.novel2video import Novel2VideoConfig

        config = Novel2VideoConfig(fps=30, resolution="1080p")
        d = config.to_dict()
        assert d["fps"] == 30
        assert d["resolution"] == "1080p"

    def test_novel2video_result(self):
        """测试 Novel2VideoResult 创建。"""
        from hevi.director.novel2video import Novel2VideoResult, Chapter

        chapters = [Chapter(1, "Ch1", "content1"), Chapter(2, "Ch2", "content2")]
        result = Novel2VideoResult(
            final_video_path=Path("/tmp/novel_video.mp4"),
            original_text="原始文本" * 100,
            chapters=chapters,
            compressed_narrative="压缩叙事",
            duration_s=120.0,
        )
        assert result.duration_s == 120.0
        assert len(result.chapters) == 2

    def test_novel2video_result_to_dict(self):
        """测试 Novel2VideoResult 序列化。"""
        from hevi.director.novel2video import Novel2VideoResult

        result = Novel2VideoResult(
            final_video_path=Path("/tmp/test.mp4"),
            original_text="测试" * 200,
            duration_s=60.0,
        )
        d = result.to_dict()
        assert d["duration_s"] == 60.0
        assert len(d["original_text"]) <= 500  # 截断

    def test_split_chapters_no_llm(self):
        """测试章节分割（无 LLM）。"""
        from hevi.director.novel2video import Novel2VideoPipeline, Novel2VideoConfig

        pipeline = Novel2VideoPipeline(config=Novel2VideoConfig())
        text = "第一章\n\n这是第一章的内容。\n\n第二章\n\n这是第二章的内容。"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(pipeline._split_chapters(text))
            assert "chapters" in result
            assert len(result["chapters"]) >= 1
        finally:
            loop.close()

    def test_extract_events_no_llm(self):
        """测试事件提取（无 LLM）。"""
        from hevi.director.novel2video import Novel2VideoPipeline, Novel2VideoConfig

        pipeline = Novel2VideoPipeline(config=Novel2VideoConfig())
        compressed = """
        ## 第一章
        相遇 | 小明遇到小红 | 小明,小红 | 咖啡馆 | 惊喜
        争吵 | 两人争执 | 小明,小红 | 街道 | 愤怒
        """

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(pipeline._extract_events(compressed))
            assert "events" in result
            assert len(result["events"]) >= 1
        finally:
            loop.close()

    def test_events_to_idea(self):
        """测试事件转换为 idea。"""
        from hevi.director.novel2video import Novel2VideoPipeline, Novel2VideoConfig, Event

        pipeline = Novel2VideoPipeline(config=Novel2VideoConfig())
        events = [
            Event(1, "两人相遇", ["小明", "小红"], "咖啡馆"),
            Event(2, "发生争执", ["小明"], "街道"),
        ]

        idea = pipeline._events_to_idea(events, "保持简短")
        assert "小明" in idea
        assert "小红" in idea
        assert "保持简短" in idea


# ═══════════════════════════════════════════════════════════════════════
# AutoCameo 测试
# ═══════════════════════════════════════════════════════════════════════


class TestAutoCameo:
    """AutoCameo 测试套件。"""

    def test_person_info_creation(self):
        """测试 PersonInfo 创建。"""
        from hevi.director.autocameo import PersonInfo

        person = PersonInfo(
            name="张三",
            description="一个高个子男人，黑色短发",
            age_estimate="30-40岁",
            gender="male",
            features=["戴眼镜", "有胡须"],
            clothing="蓝色衬衫",
        )
        assert person.name == "张三"
        assert person.gender == "male"
        assert len(person.features) == 2

    def test_person_info_to_dict(self):
        """测试 PersonInfo 序列化。"""
        from hevi.director.autocameo import PersonInfo

        person = PersonInfo(
            name="李四",
            description="年轻女性",
            age_estimate="20-30岁",
            gender="female",
        )
        d = person.to_dict()
        assert d["name"] == "李四"
        assert d["gender"] == "female"

    def test_cameo_character_creation(self):
        """测试 CameoCharacter 创建。"""
        from hevi.director.autocameo import CameoCharacter, PersonInfo

        person = PersonInfo("王五", "中年男性")
        cameo = CameoCharacter(
            character_id="cameo_01",
            person_info=person,
            reference_photo_path=Path("/tmp/photo.jpg"),
            role_in_story="protagonist",
        )
        assert cameo.character_id == "cameo_01"
        assert cameo.role_in_story == "protagonist"

    def test_cameo_character_to_dict(self):
        """测试 CameoCharacter 序列化。"""
        from hevi.director.autocameo import CameoCharacter, PersonInfo

        person = PersonInfo("赵六", "老年人")
        cameo = CameoCharacter(
            character_id="cameo_02",
            person_info=person,
            reference_photo_path=Path("/tmp/photo2.jpg"),
            role_in_story="supporting",
        )
        d = cameo.to_dict()
        assert d["character_id"] == "cameo_02"
        assert d["role_in_story"] == "supporting"

    def test_autocameo_config(self):
        """测试 AutoCameoConfig 创建。"""
        from hevi.director.autocameo import AutoCameoConfig

        config = AutoCameoConfig(
            portrait_style="cartoon",
            max_cameo_characters=5,
            face_similarity_threshold=0.8,
        )
        assert config.portrait_style == "cartoon"
        assert config.max_cameo_characters == 5
        assert config.face_similarity_threshold == 0.8

    def test_autocameo_config_to_dict(self):
        """测试 AutoCameoConfig 序列化。"""
        from hevi.director.autocameo import AutoCameoConfig

        config = AutoCameoConfig()
        d = config.to_dict()
        assert "portrait_style" in d
        assert "max_cameo_characters" in d

    def test_autocameo_result(self):
        """测试 AutoCameoResult 创建。"""
        from hevi.director.autocameo import AutoCameoResult, CameoCharacter, PersonInfo

        person = PersonInfo("测试", "测试描述")
        cameo = CameoCharacter("c1", person, Path("/tmp/p.jpg"))
        result = AutoCameoResult(
            cameo_characters=[cameo],
            integration_notes=["Added test character"],
        )
        assert len(result.cameo_characters) == 1
        assert len(result.integration_notes) == 1

    def test_autocameo_result_to_dict(self):
        """测试 AutoCameoResult 序列化。"""
        from hevi.director.autocameo import AutoCameoResult

        result = AutoCameoResult(
            integration_notes=["Note 1", "Note 2"],
        )
        d = result.to_dict()
        assert d["cameo_count"] == 0
        assert len(d["integration_notes"]) == 2

    def test_extract_person_no_llm(self):
        """测试从照片提取人物（无 LLM）。"""
        from hevi.director.autocameo import AutoCameo, AutoCameoConfig

        with tempfile.TemporaryDirectory() as td:
            photo = Path(td) / "test.jpg"
            photo.write_bytes(b"fake image data")

            autocameo = AutoCameo(config=AutoCameoConfig())

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    autocameo._extract_person_from_photo(photo)
                )
                assert "name" in result
                assert "description" in result
            finally:
                loop.close()

    def test_determine_role_no_llm(self):
        """测试确定角色定位（无 LLM）。"""
        from hevi.director.autocameo import AutoCameo, AutoCameoConfig, PersonInfo

        autocameo = AutoCameo(config=AutoCameoConfig())
        person = PersonInfo("测试人物", "测试描述")

        loop = asyncio.new_event_loop()
        try:
            role = loop.run_until_complete(
                autocameo._determine_role(person, "一个关于友谊的故事")
            )
            assert role in ["protagonist", "supporting", "cameo", "narrator"]
        finally:
            loop.close()

    def test_integrate_into_story(self):
        """测试集成到故事。"""
        from hevi.director.autocameo import AutoCameo, AutoCameoConfig, CameoCharacter, PersonInfo

        autocameo = AutoCameo(config=AutoCameoConfig())
        person = PersonInfo("客串角色", "一个特别的人物")
        cameo = CameoCharacter("c1", person, Path("/tmp/p.jpg"), role_in_story="cameo")

        story = "这是一个普通的故事。"
        new_story = autocameo.integrate_into_story(story, [cameo])

        assert "客串角色" in new_story
        assert "cameo" in new_story

    def test_integrate_empty_cameo_list(self):
        """测试空 cameo 列表。"""
        from hevi.director.autocameo import AutoCameo, AutoCameoConfig

        autocameo = AutoCameo(config=AutoCameoConfig())
        story = "原始故事"
        new_story = autocameo.integrate_into_story(story, [])

        assert new_story == story


# ═══════════════════════════════════════════════════════════════════════
# Provider Presets 测试
# ═══════════════════════════════════════════════════════════════════════


class TestProviderPresets:
    """Provider Presets 测试套件。"""

    def test_provider_preset_creation(self):
        """测试 ProviderPreset 创建。"""
        from hevi.utils.provider_presets import ProviderPreset

        preset = ProviderPreset(
            name="test_provider",
            category="llm",
            base_url="https://api.test.com",
            context_window=100000,
            default_params={"temperature": 0.5},
            api_key_env="TEST_API_KEY",
        )
        assert preset.name == "test_provider"
        assert preset.category == "llm"
        assert preset.context_window == 100000

    def test_provider_preset_to_dict(self):
        """测试 ProviderPreset 序列化。"""
        from hevi.utils.provider_presets import ProviderPreset

        preset = ProviderPreset(
            name="test",
            category="video",
            base_url="https://test.com",
        )
        d = preset.to_dict()
        assert d["name"] == "test"
        assert d["category"] == "video"

    def test_get_preset_llm(self):
        """测试获取 LLM preset。"""
        from hevi.utils.provider_presets import get_preset

        preset = get_preset("openai", category="llm")
        assert preset is not None
        assert preset.name == "openai"
        assert preset.category == "llm"
        assert "openai.com" in preset.base_url

    def test_get_preset_image(self):
        """测试获取 Image preset。"""
        from hevi.utils.provider_presets import get_preset

        preset = get_preset("openai_dalle", category="image")
        assert preset is not None
        assert preset.category == "image"

    def test_get_preset_video(self):
        """测试获取 Video preset。"""
        from hevi.utils.provider_presets import get_preset

        preset = get_preset("veo", category="video")
        assert preset is not None
        assert preset.category == "video"

    def test_get_preset_auto_category(self):
        """测试自动类别检测。"""
        from hevi.utils.provider_presets import get_preset

        preset = get_preset("anthropic")
        assert preset is not None
        assert preset.name == "anthropic"

    def test_get_preset_not_found(self):
        """测试未找到 preset。"""
        from hevi.utils.provider_presets import get_preset

        preset = get_preset("nonexistent_provider")
        assert preset is None

    def test_list_presets_llm(self):
        """测试列出 LLM presets。"""
        from hevi.utils.provider_presets import list_presets

        presets = list_presets(category="llm")
        assert "openai" in presets
        assert "anthropic" in presets
        assert len(presets) >= 5

    def test_list_presets_all(self):
        """测试列出所有 presets。"""
        from hevi.utils.provider_presets import list_presets

        presets = list_presets()
        assert len(presets) >= 10  # LLM + Image + Video

    def test_resolve_config_with_preset(self):
        """测试配置合并（有 preset）。"""
        from hevi.utils.provider_presets import resolve_config

        user_config = {
            "model": "gpt-4o",
            "temperature": 0.9,  # 覆盖默认值
        }
        resolved = resolve_config("openai", user_config, category="llm")

        assert resolved["model"] == "gpt-4o"
        assert resolved["temperature"] == 0.9  # 用户值优先
        assert "base_url" in resolved  # 从 preset 继承

    def test_resolve_config_no_preset(self):
        """测试配置合并（无 preset）。"""
        from hevi.utils.provider_presets import resolve_config

        user_config = {"custom_param": "value"}
        resolved = resolve_config("unknown_provider", user_config)

        assert resolved == user_config  # 原样返回

    def test_resolve_chat_model_config(self):
        """测试聊天模型配置解析。"""
        from hevi.utils.provider_presets import resolve_chat_model_config

        config = resolve_chat_model_config(
            model="gpt-4o",
            provider="openai",
            api_key="sk-test",
        )
        assert config["model"] == "gpt-4o"
        assert config["provider"] == "openai"
        assert config["api_key"] == "sk-test"
        assert "base_url" in config

    def test_resolve_image_generator_config(self):
        """测试图像生成器配置解析。"""
        from hevi.utils.provider_presets import resolve_image_generator_config

        config = resolve_image_generator_config(
            provider="stability",
            api_key="test-key",
            width=512,
        )
        assert config["provider"] == "stability"
        assert config["api_key"] == "test-key"
        assert config["width"] == 512  # 用户值覆盖

    def test_resolve_video_generator_config(self):
        """测试视频生成器配置解析。"""
        from hevi.utils.provider_presets import resolve_video_generator_config

        config = resolve_video_generator_config(
            provider="veo",
            duration_s=10,
        )
        assert config["provider"] == "veo"
        assert config["duration_s"] == 10
        assert "base_url" in config


# ═══════════════════════════════════════════════════════════════════════
# Prompt Builder 测试
# ═══════════════════════════════════════════════════════════════════════


class TestPromptBuilder:
    """Prompt Builder 测试套件。"""

    def test_prompt_part_creation(self):
        """测试 PromptPart 创建。"""
        from hevi.agent_runtime.prompt_builder import PromptPart

        part = PromptPart(
            name="test_part",
            content="测试内容",
            priority=10,
            enabled=True,
        )
        assert part.name == "test_part"
        assert part.priority == 10
        assert part.enabled

    def test_prompt_part_to_dict(self):
        """测试 PromptPart 序列化。"""
        from hevi.agent_runtime.prompt_builder import PromptPart

        part = PromptPart("test", "很长的内容" * 100, priority=5)
        d = part.to_dict()
        assert d["name"] == "test"
        assert d["priority"] == 5
        assert len(d["content"]) <= 200  # 截断

    def test_prompt_context_creation(self):
        """测试 PromptContext 创建。"""
        from hevi.agent_runtime.prompt_builder import PromptContext

        context = PromptContext(
            session_id="abc123",
            project_name="测试项目",
            artifacts=[{"name": "video.mp4", "path": "/tmp/video.mp4"}],
            checklist=["任务1", "任务2"],
            previous_summary="之前的对话摘要",
        )
        assert context.session_id == "abc123"
        assert len(context.artifacts) == 1
        assert len(context.checklist) == 2

    def test_prompt_context_to_dict(self):
        """测试 PromptContext 序列化。"""
        from hevi.agent_runtime.prompt_builder import PromptContext

        context = PromptContext(
            session_id="test",
            artifacts=[{"name": "a"}, {"name": "b"}],
        )
        d = context.to_dict()
        assert d["session_id"] == "test"
        assert d["artifact_count"] == 2

    def test_tool_info_creation(self):
        """测试 ToolInfo 创建。"""
        from hevi.agent_runtime.prompt_builder import ToolInfo

        tool = ToolInfo(
            name="generate_video",
            description="生成视频",
            parameters={
                "prompt": {"type": "string", "description": "提示词", "required": True},
                "duration": {"type": "number", "description": "时长"},
            },
        )
        assert tool.name == "generate_video"
        assert len(tool.parameters) == 2

    def test_tool_info_to_prompt_text(self):
        """测试 ToolInfo 转换为 prompt 文本。"""
        from hevi.agent_runtime.prompt_builder import ToolInfo

        tool = ToolInfo(
            name="test_tool",
            description="测试工具",
            parameters={
                "param1": {"type": "string", "description": "参数1", "required": True},
            },
        )
        text = tool.to_prompt_text()
        assert "test_tool" in text
        assert "测试工具" in text
        assert "param1" in text
        assert "(必需)" in text

    def test_prompt_builder_basic(self):
        """测试 PromptBuilder 基本使用。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        builder.add_template("你是 Hevi 助手。")

        prompt = builder.build()
        assert "Hevi" in prompt

    def test_prompt_builder_with_context(self):
        """测试 PromptBuilder 带上下文。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder, PromptContext

        builder = PromptBuilder()
        builder.add_template("基础模板")

        context = PromptContext(
            session_id="test123",
            project_name="测试项目",
        )
        builder.set_context(context)

        prompt = builder.build()
        assert "test123" in prompt
        assert "测试项目" in prompt

    def test_prompt_builder_with_tools(self):
        """测试 PromptBuilder 带工具列表。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder, ToolInfo

        builder = PromptBuilder()
        builder.add_template("你可以使用以下工具：")

        tools = [
            ToolInfo("tool1", "工具1"),
            ToolInfo("tool2", "工具2"),
        ]
        builder.add_tools(tools)

        prompt = builder.build()
        assert "tool1" in prompt
        assert "tool2" in prompt

    def test_prompt_builder_variable_substitution(self):
        """测试 PromptBuilder 变量替换。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        builder.add_template("你好，{username}！欢迎使用 {product}。")
        builder.set_variable("username", "张三")
        builder.set_variable("product", "Hevi")

        prompt = builder.build()
        assert "张三" in prompt
        assert "Hevi" in prompt
        assert "{username}" not in prompt

    def test_prompt_builder_priority_ordering(self):
        """测试 PromptBuilder 优先级排序。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        builder.add_template("低优先级", priority=1)
        builder.add_template("高优先级", priority=100)
        builder.add_template("中优先级", priority=50)

        prompt = builder.build()
        high_pos = prompt.find("高优先级")
        mid_pos = prompt.find("中优先级")
        low_pos = prompt.find("低优先级")

        assert high_pos < mid_pos < low_pos

    def test_build_vimax_agent_prompt(self):
        """测试构建 ViMax agent prompt。"""
        from hevi.agent_runtime.prompt_builder import build_vimax_agent_prompt, ToolInfo

        tools = [ToolInfo("test", "测试工具")]
        prompt = build_vimax_agent_prompt(
            session_id="test_session",
            project_name="测试项目",
            previous_summary="之前的摘要",
            tools=tools,
        )

        assert "Hevi" in prompt
        assert "test_session" in prompt
        assert "测试项目" in prompt
        assert "之前的摘要" in prompt
        assert "test" in prompt

    def test_build_pipeline_prompt(self):
        """测试构建管线 prompt。"""
        from hevi.agent_runtime.prompt_builder import build_pipeline_prompt, PromptContext

        context = PromptContext(session_id="pipeline_test")
        prompt = build_pipeline_prompt("idea2video", context)

        assert "idea2video" in prompt
        assert "pipeline_test" in prompt

    def test_prompt_builder_chaining(self):
        """测试 PromptBuilder 链式调用。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder, PromptContext

        prompt = (
            PromptBuilder()
            .add_template("模板1")
            .add_template("模板2")
            .set_context(PromptContext(session_id="test"))
            .set_variable("key", "value")
            .build()
        )

        assert "模板1" in prompt
        assert "模板2" in prompt
        assert "test" in prompt

    def test_prompt_builder_clear(self):
        """测试 PromptBuilder 清空。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder

        builder = PromptBuilder()
        builder.add_template("测试")
        builder.set_variable("key", "value")

        builder.clear()
        prompt = builder.build()

        assert prompt == ""

    def test_prompt_builder_clone(self):
        """测试 PromptBuilder 克隆。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder

        builder1 = PromptBuilder()
        builder1.add_template("原始模板")

        builder2 = builder1.clone()
        builder2.add_template("新模板")

        prompt1 = builder1.build()
        prompt2 = builder2.build()

        assert "原始模板" in prompt1
        assert "新模板" not in prompt1
        assert "原始模板" in prompt2
        assert "新模板" in prompt2

    def test_prompt_builder_to_dict(self):
        """测试 PromptBuilder 导出配置。"""
        from hevi.agent_runtime.prompt_builder import PromptBuilder, PromptContext

        builder = PromptBuilder()
        builder.add_template("测试")
        builder.set_context(PromptContext(session_id="test"))
        builder.set_variable("key", "value")

        d = builder.to_dict()
        assert "parts" in d
        assert "context" in d
        assert "variables" in d


# ═══════════════════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════════════════


class TestViMaxBatch4Integration:
    """ViMax Batch 4 集成测试。"""

    def test_novel2video_with_autocameo(self):
        """测试 Novel2Video + AutoCameo 集成。"""
        from hevi.director.novel2video import Novel2VideoPipeline, Novel2VideoConfig
        from hevi.director.autocameo import AutoCameo, AutoCameoConfig

        with tempfile.TemporaryDirectory() as td:
            novel_pipeline = Novel2VideoPipeline(
                config=Novel2VideoConfig(working_dir=Path(td) / "novel")
            )
            autocameo = AutoCameo(config=AutoCameoConfig(working_dir=Path(td) / "cameo"))

            # 两个管线可以独立工作
            assert novel_pipeline.config.working_dir != autocameo.config.working_dir

    def test_provider_presets_with_render_backend(self):
        """测试 Provider Presets + Render Backend 集成。"""
        from hevi.utils.provider_presets import resolve_video_generator_config
        from hevi.director.render_backend import RenderBackendConfig

        # 从 preset 获取配置
        video_config = resolve_video_generator_config(provider="veo", duration_s=8)

        # 用于 RenderBackendConfig
        backend_config = RenderBackendConfig(
            video_generator={
                "class_path": "hevi.video.provider_veo.generate_veo_clip",
                "init_args": video_config,
            }
        )

        assert backend_config.video_generator is not None

    def test_prompt_builder_with_agent_loop(self):
        """测试 Prompt Builder + Agent Loop 集成。"""
        from hevi.agent_runtime.prompt_builder import build_vimax_agent_prompt, ToolInfo
        from hevi.agent_runtime.loop import AgentLoop, ToolRegistry

        # 构建 prompt
        tools = [ToolInfo("test_tool", "测试工具")]
        system_prompt = build_vimax_agent_prompt(
            session_id="integration_test",
            tools=tools,
        )

        # 创建 AgentLoop
        async def mock_llm(messages, tools_schema):
            return "响应", []

        registry = ToolRegistry()
        loop = AgentLoop(
            llm_caller=mock_llm,
            tool_registry=registry,
            system_prompt=system_prompt,
        )

        assert loop.system_prompt == system_prompt
        assert "integration_test" in loop.system_prompt

    def test_all_imports(self):
        """测试所有新增模块可导入。"""
        from hevi.director import (
            Novel2VideoConfig,
            Novel2VideoPipeline,
            Novel2VideoResult,
            AutoCameo,
            AutoCameoConfig,
            AutoCameoResult,
            CameoCharacter,
        )
        from hevi.utils import (
            ProviderPreset,
            get_preset,
            list_presets,
            resolve_config,
        )
        from hevi.agent_runtime import (
            PromptBuilder,
            PromptContext,
            PromptPart,
            ToolInfo,
            build_vimax_agent_prompt,
        )

        assert Novel2VideoPipeline is not None
        assert AutoCameo is not None
        assert get_preset is not None
        assert PromptBuilder is not None

    def test_full_workflow_mock(self):
        """测试完整工作流（mock）。"""
        from hevi.director.novel2video import Novel2VideoPipeline, Novel2VideoConfig
        from hevi.director.autocameo import AutoCameo, AutoCameoConfig, PersonInfo, CameoCharacter
        from hevi.utils.provider_presets import resolve_chat_model_config
        from hevi.agent_runtime.prompt_builder import build_vimax_agent_prompt

        with tempfile.TemporaryDirectory() as td:
            # 1. 配置 provider
            llm_config = resolve_chat_model_config(
                model="gpt-4o",
                provider="openai",
                api_key="test-key",
            )

            # 2. 构建 prompt
            system_prompt = build_vimax_agent_prompt(
                session_id="workflow_test",
                project_name="完整工作流测试",
            )

            # 3. 创建 Novel2Video 管线
            novel_pipeline = Novel2VideoPipeline(
                config=Novel2VideoConfig(working_dir=Path(td))
            )

            # 4. 创建 AutoCameo
            autocameo = AutoCameo(config=AutoCameoConfig())

            # 5. 创建 cameo 角色
            person = PersonInfo("测试角色", "测试描述")
            cameo = CameoCharacter("c1", person, Path("/tmp/photo.jpg"))

            # 6. 集成到故事
            story = "这是一个测试故事。"
            new_story = autocameo.integrate_into_story(story, [cameo])

            assert "测试角色" in new_story
            assert llm_config["model"] == "gpt-4o"
            assert "workflow_test" in system_prompt
