"""发布工作室 5 模块全量测试。

覆盖:
  1. 多平台发布 (publisher)
  2. 动效模板 (motion)
  3. HTML 视频管线 (html-video)
  4. OmniVoice 本地语音 (omnivoice)
  5. Wan-Dancer 编舞 (dance)

Run: .venv/bin/python -m pytest tests/test_publish_studio.py --noconftest -q
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


# ===================================================================
# 1. Multi-platform Publisher
# ===================================================================

class TestPublisher:

    @pytest.mark.asyncio
    async def test_platform_configs(self):
        from hevi.publisher import PublishPlatform, get_platform_config
        for platform in PublishPlatform:
            config = get_platform_config(platform)
            assert config.platform == platform
            assert config.title_limit > 0
            assert config.publish_url

    @pytest.mark.asyncio
    async def test_publish_video_pre_publish(self):
        from hevi.publisher import (
            PublishPlatform, PublishTask, PublishStatus,
            publish_video, get_platform_config,
        )
        task = PublishTask(
            platform=PublishPlatform.xiaohongshu,
            video_path="/tmp/test.mp4",
            title="测试视频",
            auto_publish=False,
        )
        config = get_platform_config(PublishPlatform.xiaohongshu)
        result = await publish_video(task, config)
        assert result.status == PublishStatus.ready_to_publish
        assert result.published_url is None

    @pytest.mark.asyncio
    async def test_publish_video_auto_publish(self):
        from hevi.publisher import (
            PublishPlatform, PublishTask, PublishStatus, publish_video,
        )
        task = PublishTask(
            platform=PublishPlatform.douyin,
            video_path="/tmp/test.mp4",
            title="抖音测试",
            auto_publish=True,
        )
        result = await publish_video(task)
        assert result.status == PublishStatus.published
        assert result.published_url is not None

    @pytest.mark.asyncio
    async def test_publish_batch(self):
        from hevi.publisher import (
            PublishPlatform, PublishTask, PublishBatchRequest,
            publish_batch, PublishStatus,
        )
        tasks = [
            PublishTask(platform=PublishPlatform.xiaohongshu, video_path="/tmp/1.mp4", title="XHS"),
            PublishTask(platform=PublishPlatform.bilibili, video_path="/tmp/2.mp4", title="Bili"),
            PublishTask(platform=PublishPlatform.wechat_video, video_path="/tmp/3.mp4", title="WeChat"),
        ]
        request = PublishBatchRequest(tasks=tasks, auto_publish=True, max_parallel=2)
        result = await publish_batch(request)
        assert result.total == 3
        assert result.succeeded == 3
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_confirm_publish(self):
        from hevi.publisher import (
            PublishPlatform, PublishTask, PublishStatus,
            publish_video, confirm_publish,
        )
        task = PublishTask(
            platform=PublishPlatform.bilibili,
            video_path="/tmp/test.mp4",
            title="B站",
            auto_publish=False,
        )
        result = await publish_video(task)
        assert result.status == PublishStatus.ready_to_publish

        confirmed = await confirm_publish(result.id)
        assert confirmed is not None
        assert confirmed.status == PublishStatus.published

    @pytest.mark.asyncio
    async def test_schedule_publish(self):
        from datetime import datetime, timedelta
        from hevi.publisher import (
            PublishPlatform, PublishTask, PublishStatus, schedule_publish,
        )
        task = PublishTask(
            platform=PublishPlatform.youtube,
            video_path="/tmp/test.mp4",
            title="Scheduled",
        )
        future = datetime.utcnow() + timedelta(hours=1)
        task_id = await schedule_publish(task, future)
        assert task_id == task.id

    @pytest.mark.asyncio
    async def test_cookie_store(self):
        import tempfile
        from hevi.publisher.cookie_manager import CookieStore, CookieStatus
        with tempfile.TemporaryDirectory() as tmp:
            store = CookieStore(cookies_dir=tmp)
            # Save cookies
            store.save_cookies("xiaohongshu", [{"name": "session", "value": "abc"}])
            # Load
            cookies = store.load_cookies("xiaohongshu")
            assert cookies is not None
            assert len(cookies) == 1
            # Validate
            status = store.validate("xiaohongshu")
            assert status == CookieStatus.valid
            # Missing platform
            assert store.validate("unknown") == CookieStatus.missing
            # List
            platforms = store.list_platforms()
            assert "xiaohongshu" in platforms
            # Clear
            store.clear("xiaohongshu")
            assert store.load_cookies("xiaohongshu") is None

    @pytest.mark.asyncio
    async def test_scheduler(self):
        from datetime import datetime, timedelta
        from hevi.publisher.scheduler import PublishScheduler
        from hevi.publisher import PublishPlatform, PublishTask, PublishStatus

        scheduler = PublishScheduler(poll_interval=0.1)
        task = PublishTask(
            platform=PublishPlatform.douyin,
            video_path="/tmp/test.mp4",
            title="Scheduled",
        )
        task_id = scheduler.add(task, datetime.utcnow() - timedelta(seconds=1))
        assert scheduler.get_pending()
        assert scheduler.cancel(task_id)
        assert not scheduler.get_pending()

    @pytest.mark.asyncio
    async def test_platform_title_limits(self):
        from hevi.publisher import PublishPlatform, get_platform_config
        # XHS max 20
        assert get_platform_config(PublishPlatform.xiaohongshu).title_limit == 20
        # Douyin max 55
        assert get_platform_config(PublishPlatform.douyin).title_limit == 55
        # Bilibili max 80
        assert get_platform_config(PublishPlatform.bilibili).title_limit == 80
        # WeChat max 30
        assert get_platform_config(PublishPlatform.wechat_video).title_limit == 30


# ===================================================================
# 2. Motion Templates
# ===================================================================

class TestMotionTemplates:

    def test_catalog_has_20_templates(self):
        from hevi.video.motion_templates import get_catalog
        catalog = get_catalog()
        assert len(catalog.templates) == 20

    def test_catalog_categories(self):
        from hevi.video.motion_templates import get_catalog
        catalog = get_catalog()
        cats = catalog.categories
        # Categories may use full names
        assert len(cats) >= 3
        assert any("Data" in c or "data" in c for c in cats)
        assert any("Overlay" in c or "overlay" in c for c in cats)

    def test_search_by_query(self):
        from hevi.video.motion_templates import get_catalog
        catalog = get_catalog()
        results = catalog.search(query="数字")
        assert len(results) >= 1

    def test_get_template(self):
        from hevi.video.motion_templates import get_template
        t = get_template("metric-pulse")
        assert t.id == "metric-pulse"
        assert t.name == "数字跳动计数器"
        assert len(t.variables) > 0

    def test_get_template_invalid(self):
        from hevi.video.motion_templates import get_template
        with pytest.raises((ValueError, KeyError)):
            get_template("nonexistent")

    def test_list_presets(self):
        from hevi.video.motion_templates import list_presets
        presets = list_presets("metric-pulse")
        assert len(presets) >= 1

    def test_template_html_has_content(self):
        from hevi.video.motion_templates import get_template
        t = get_template("lower-third")
        assert t.html_source  # has HTML content
        assert len(t.html_source) > 20

    def test_transparent_templates(self):
        from hevi.video.motion_templates import get_catalog
        catalog = get_catalog()
        transparent = [t for t in catalog.templates if t.supports_transparent]
        assert len(transparent) >= 4

    @pytest.mark.asyncio
    async def test_render_motion_request(self):
        from hevi.video.motion_templates import MotionRenderRequest, MotionRenderResult
        req = MotionRenderRequest(
            template_id="metric-pulse",
            variables={"value": 9999, "label": "TEST"},
        )
        assert req.template_id == "metric-pulse"
        assert req.variables["value"] == 9999


# ===================================================================
# 3. HTML Video Pipeline
# ===================================================================

class TestHtmlVideoPipeline:

    def test_list_html_templates(self):
        from hevi.video.html_templates import list_html_templates
        templates = list_html_templates()
        assert len(templates) == 21

    def test_get_html_template(self):
        from hevi.video.html_templates import get_html_template
        t = get_html_template("tweet-card")
        assert t.id == "tweet-card"
        assert len(t.variables) > 0

    def test_get_html_template_invalid(self):
        from hevi.video.html_templates import get_html_template
        with pytest.raises(ValueError):
            get_html_template("nonexistent")

    def test_template_categories(self):
        from hevi.video.html_templates import list_html_templates
        templates = list_html_templates()
        cats = set(t.category for t in templates)
        assert "social" in cats
        assert "explainer" in cats
        assert "marketing" in cats
        assert "data" in cats
        assert "creative" in cats

    def test_parse_script_to_graph(self):
        from hevi.video.content_graph import parse_script_to_graph, ContentNodeType
        script = """# Welcome
This is the intro paragraph.

## Chapter 1
- First point
- Second point

## Chapter 2
- Third point"""
        graph = parse_script_to_graph(script)
        assert len(graph.nodes) >= 5
        types = [n.type for n in graph.nodes]
        assert ContentNodeType.title in types
        assert ContentNodeType.subtitle in types

    def test_graph_to_storyboard(self):
        from hevi.video.content_graph import parse_script_to_graph, graph_to_storyboard
        script = "# Title\nSome content\n\n## Chapter\n- Point"
        graph = parse_script_to_graph(script)
        sb = graph_to_storyboard(graph)
        assert len(sb.frames) >= 2
        assert sb.total_duration > 0
        assert sb.resolution == (1920, 1080)

    def test_html_video_request_model(self):
        from hevi.video.html_video_pipeline import HtmlVideoRequest
        req = HtmlVideoRequest(template_id="tweet-card", data={"name": "Test"})
        assert req.template_id == "tweet-card"
        assert req.data["name"] == "Test"

    def test_html_video_request_model(self):
        from hevi.video.html_video_pipeline import HtmlVideoRequest
        req = HtmlVideoRequest(template_id="tweet-card", data={"title": "Test"})
        assert req.template_id == "tweet-card"

    def test_storyboard_frame_model(self):
        from hevi.video.content_graph import StoryboardFrame
        frame = StoryboardFrame(frame_index=0, duration=3.0, html_template="<div>test</div>")
        assert frame.frame_index == 0
        assert frame.transition_in == "fade"

    def test_vertical_aspect_ratio(self):
        from hevi.video.content_graph import parse_script_to_graph, graph_to_storyboard
        script = "# Title\nContent"
        graph = parse_script_to_graph(script, aspect_ratio="9:16")
        sb = graph_to_storyboard(graph)
        assert sb.resolution == (1080, 1920)


# ===================================================================
# 4. OmniVoice Local Pipeline
# ===================================================================

class TestOmniVoice:

    @pytest.mark.asyncio
    async def test_clone_voice_missing_ref(self):
        from hevi.audio.omnivoice_service import VoiceCloneRequest, clone_voice
        req = VoiceCloneRequest(
            reference_audio_path="/nonexistent/audio.wav",
            target_text="测试",
        )
        result = await clone_voice(req)
        assert not result.success
        assert "not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_clone_voice_with_file(self):
        import tempfile
        from hevi.audio.omnivoice_service import VoiceCloneRequest, clone_voice
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF" + b"\x00" * 100)
            ref_path = f.name

        out_path = f"/tmp/test_clone_{id(f)}.wav"
        req = VoiceCloneRequest(
            reference_audio_path=ref_path,
            target_text="你好世界",
            language="zh",
            output_path=out_path,
        )
        result = await clone_voice(req)
        assert result.success
        assert result.voice_id.startswith("clone_")
        assert result.similarity_score > 0

    @pytest.mark.asyncio
    async def test_dub_video_missing_source(self):
        from hevi.audio.omnivoice_service import DubRequest, dub_video
        req = DubRequest(source_video_path="/nonexistent/video.mp4", target_language="en")
        result = await dub_video(req)
        assert not result.success

    @pytest.mark.asyncio
    async def test_generate_audiobook(self):
        from hevi.audio.omnivoice_service import AudiobookRequest, generate_audiobook
        import random
        req = AudiobookRequest(
            text_or_path="第一章\n这是第一段内容。\n\n第二章\n这是第二段内容。",
            voice_id="default",
            output_path=f"/tmp/test_audiobook_{random.randint(1000,9999)}.mp3",
        )
        result = await generate_audiobook(req)
        assert result.success
        assert result.chapters_count >= 1

    @pytest.mark.asyncio
    async def test_dictate_missing_audio(self):
        from hevi.audio.omnivoice_service import DictationRequest, dictate
        req = DictationRequest(audio_path="/nonexistent/audio.wav")
        result = await dictate(req)
        assert not result.success

    @pytest.mark.asyncio
    async def test_diarize_missing_audio(self):
        from hevi.audio.omnivoice_service import DiarizeRequest, diarize
        req = DiarizeRequest(audio_path="/nonexistent/audio.wav")
        result = await diarize(req)
        assert not result.success

    @pytest.mark.asyncio
    async def test_design_voice(self):
        import random
        from hevi.audio.omnivoice_service import VoiceDesignRequest, design_voice
        req = VoiceDesignRequest(
            description="warm female voice",
            gender="female",
            age_range="adult",
            output_path=f"/tmp/test_design_{random.randint(1000,9999)}.wav",
        )
        result = await design_voice(req)
        assert result.success
        assert result.voice_id.startswith("design_")

    @pytest.mark.asyncio
    async def test_list_and_get_voices(self):
        import random
        from hevi.audio.omnivoice_service import (
            VoiceDesignRequest, design_voice, list_local_voices, get_voice_info,
        )
        req = VoiceDesignRequest(description="test voice", output_path=f"/tmp/test_list_{random.randint(1000,9999)}.wav")
        result = await design_voice(req)
        voices = list_local_voices()
        assert len(voices) >= 1
        info = get_voice_info(result.voice_id)
        assert info is not None
        assert info["voice_id"] == result.voice_id

    def test_auto_split_chapters(self):
        from hevi.audio.omnivoice_service import _auto_split_chapters
        text = "# Chapter 1\nContent one.\n\n# Chapter 2\nContent two.\n\n# Chapter 3\nContent three."
        chapters = _auto_split_chapters(text)
        assert len(chapters) >= 3

    @pytest.mark.asyncio
    async def test_watermark_embed(self):
        import tempfile, random
        from hevi.audio.watermark import AudioWatermarker
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF" + b"\x00" * 100)
            audio_path = Path(f.name)

        wm = AudioWatermarker()
        output = Path(f"/tmp/test_wm_{random.randint(1000,9999)}.wav")
        result = await wm.embed(audio_path, "hevi-watermark", output)
        assert result.exists()

    @pytest.mark.asyncio
    async def test_watermark_detect_missing(self):
        from hevi.audio.watermark import detect_watermark
        result = await detect_watermark(Path("/nonexistent/audio.wav"))
        assert result is None


# ===================================================================
# 5. Wan-Dancer
# ===================================================================

class TestWanDancer:

    def test_supported_genres(self):
        from hevi.video.provider_wan_dancer import supported_genres, DanceGenre
        genres = supported_genres()
        assert len(genres) == 5
        assert DanceGenre.chinese_classical in genres
        assert DanceGenre.kpop in genres
        assert DanceGenre.street in genres
        assert DanceGenre.tap in genres
        assert DanceGenre.latin in genres

    def test_check_gpu_requirements(self):
        from hevi.video.provider_wan_dancer import check_gpu_requirements
        info = check_gpu_requirements()
        assert "available" in info
        assert "required" in info
        assert info["required"] == "8 GPUs"

    def test_estimate_render_time(self):
        from hevi.video.provider_wan_dancer import estimate_render_time
        t720 = estimate_render_time(60.0, "720p")
        assert t720 > 0
        t1080 = estimate_render_time(60.0, "1080p")
        assert t1080 > t720
        t480 = estimate_render_time(60.0, "480p")
        assert t480 < t720

    @pytest.mark.asyncio
    async def test_plan_keyframes(self):
        import tempfile
        from hevi.video.provider_wan_dancer import plan_keyframes, DanceGenre
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"\x00" * 100)
            music_path = f.name

        plan = await plan_keyframes(music_path, DanceGenre.kpop, 30.0)
        assert len(plan.global_keyframes) > 0
        assert len(plan.local_refinements) > 0
        # First keyframe starts at t=0
        assert plan.global_keyframes[0]["time"] == 0.0
        # Intensity increases over time
        if len(plan.global_keyframes) > 1:
            assert plan.global_keyframes[-1]["intensity"] > plan.global_keyframes[0]["intensity"]

    @pytest.mark.asyncio
    async def test_plan_keyframes_missing_music(self):
        from hevi.video.provider_wan_dancer import plan_keyframes, DanceGenre
        with pytest.raises(FileNotFoundError):
            await plan_keyframes("/nonexistent/music.mp3", DanceGenre.kpop, 30.0)

    @pytest.mark.asyncio
    async def test_generate_dance_video(self):
        import tempfile, random
        from hevi.video.provider_wan_dancer import (
            generate_dance_video, WanDancerRequest, DanceGenre, DanceCharacter,
        )
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"\x00" * 100)
            music_path = f.name

        req = WanDancerRequest(
            music_path=music_path,
            genre=DanceGenre.kpop,
            duration=10.0,
            character=DanceCharacter(name="TestDancer"),
            output_path=f"/tmp/test_dance_{random.randint(1000,9999)}.mp4",
        )
        result = await generate_dance_video(req)
        assert result.success
        assert result.genre == "kpop"
        assert result.keyframes_used > 0

    def test_genre_vocabulary(self):
        from hevi.video.provider_wan_dancer import _GENRE_VOCABULARY, DanceGenre
        for genre in DanceGenre:
            vocab = _GENRE_VOCABULARY[genre]
            assert "poses" in vocab
            assert len(vocab["poses"]) >= 3
            assert "movement_style" in vocab

    def test_dance_request_model(self):
        from hevi.video.provider_wan_dancer import WanDancerRequest, DanceGenre
        req = WanDancerRequest(
            music_path="/tmp/music.mp3",
            genre=DanceGenre.latin,
            duration=45.0,
        )
        assert req.genre == DanceGenre.latin
        assert req.resolution == "720p"
        assert req.fps == 30


# ===================================================================
# 6. Video __init__ exports
# ===================================================================

class TestVideoExports:

    def test_wan_dancer_exports(self):
        from hevi.video import DanceGenre, WanDancerRequest, generate_dance_video
        assert DanceGenre is not None

    def test_motion_template_exports(self):
        from hevi.video import MotionCatalog, get_motion_catalog, render_motion
        assert get_motion_catalog is not None

    def test_html_video_exports(self):
        from hevi.video import (
            HtmlVideoRequest, HtmlVideoTemplate, list_html_templates,
            parse_script_to_graph, graph_to_storyboard,
        )
        assert len(list_html_templates()) == 21

    def test_content_graph_exports(self):
        from hevi.video import ContentGraph, Storyboard, parse_script_to_graph
        graph = parse_script_to_graph("# Hello\nWorld")
        assert isinstance(graph, ContentGraph)


# ===================================================================
# 7. Audio __init__ exports
# ===================================================================

class TestAudioExports:

    def test_omnivoice_exports(self):
        from hevi.audio import (
            clone_voice, dub_video, generate_audiobook, dictate, diarize,
            design_voice, list_local_voices, VoiceCloneRequest,
        )
        assert clone_voice is not None
        assert VoiceCloneRequest is not None

    def test_watermark_exports(self):
        from hevi.audio import AudioWatermarker, embed_watermark, detect_watermark
        assert AudioWatermarker is not None
        assert embed_watermark is not None
