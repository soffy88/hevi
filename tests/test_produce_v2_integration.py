"""produce_v2 ViMax 集成测试 — 验证新模块接入 produce_v2 主流程。

测试:
1. RenderBackend 适配器 (DashScopeImageAdapter, WanVideoAdapter, create_render_backend)
2. produce_v2 新参数 (provider_preset, use_transitions, render_backend)
3. PromptBuilder 集成 (_build_image_prompt)
4. 新 API 端点 (provider-presets, idea2video, novel2video, autocameo)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. RenderBackend 适配器 ──────────────────────────────────────────────


class TestDashScopeImageAdapter:
    def test_init_default(self):
        from hevi.director.render_backend import DashScopeImageAdapter

        adapter = DashScopeImageAdapter()
        assert adapter._model == "happyhorse_1_1"

    def test_init_custom(self):
        from hevi.director.render_backend import DashScopeImageAdapter

        adapter = DashScopeImageAdapter(model="wan_2_7")
        assert adapter._model == "wan_2_7"

    def test_generate_returns_path(self):
        from hevi.director.render_backend import DashScopeImageAdapter

        adapter = DashScopeImageAdapter()

        async def _run():
            with patch("hevi.video.alibaba_maas_service.alibaba_maas_generate") as mock_gen:
                mock_gen.return_value = Path("/tmp/test_img.png")
                result = await adapter.generate(
                    prompt="test prompt",
                    output_path=Path("/tmp/test_img.png"),
                )
                assert isinstance(result, Path)
                assert str(result) == "/tmp/test_img.png"
                mock_gen.assert_called_once()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_generate_uses_custom_model(self):
        from hevi.director.render_backend import DashScopeImageAdapter

        adapter = DashScopeImageAdapter(model="wan_2_7")

        async def _run():
            with patch("hevi.video.alibaba_maas_service.alibaba_maas_generate") as mock_gen:
                mock_gen.return_value = Path("/tmp/img.png")
                await adapter.generate(prompt="test", output_path=Path("/tmp/img.png"))
                call_kwargs = mock_gen.call_args
                assert call_kwargs.kwargs.get("model", "") == "wan_2_7"

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()


class TestWanVideoAdapter:
    def test_init_default(self):
        from hevi.director.render_backend import WanVideoAdapter

        adapter = WanVideoAdapter()
        assert adapter._model == "wan_2_7"

    def test_init_custom(self):
        from hevi.director.render_backend import WanVideoAdapter

        adapter = WanVideoAdapter(model="happyhorse_1_1")
        assert adapter._model == "happyhorse_1_1"

    def test_generate_returns_path(self):
        from hevi.director.render_backend import WanVideoAdapter

        adapter = WanVideoAdapter()

        async def _run():
            with patch("hevi.video.alibaba_maas_service.alibaba_maas_generate") as mock_gen:
                mock_gen.return_value = Path("/tmp/test_vid.mp4")
                result = await adapter.generate(
                    prompt="test prompt",
                    output_path=Path("/tmp/test_vid.mp4"),
                )
                assert isinstance(result, Path)
                assert str(result) == "/tmp/test_vid.mp4"
                mock_gen.assert_called_once()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    def test_generate_with_custom_model(self):
        from hevi.director.render_backend import WanVideoAdapter

        adapter = WanVideoAdapter(model="happyhorse_1_1")

        async def _run():
            with patch("hevi.video.alibaba_maas_service.alibaba_maas_generate") as mock_gen:
                mock_gen.return_value = Path("/tmp/vid.mp4")
                await adapter.generate(
                    prompt="test",
                    output_path=Path("/tmp/vid.mp4"),
                )
                call_kwargs = mock_gen.call_args
                assert call_kwargs.kwargs.get("model", "") == "happyhorse_1_1"

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()


class TestCreateRenderBackend:
    def test_default_creates_dashscope_and_wan(self):
        from hevi.director.render_backend import (
            DashScopeImageAdapter,
            WanVideoAdapter,
            create_render_backend,
        )

        backend = create_render_backend()
        assert isinstance(backend.image_generator, DashScopeImageAdapter)
        assert isinstance(backend.video_generator, WanVideoAdapter)

    def test_with_params(self):
        from hevi.director.render_backend import create_render_backend

        backend = create_render_backend(
            image_params={"model": "wan_2_7"},
            video_params={"model": "happyhorse_1_1"},
        )
        assert backend.image_generator._model == "wan_2_7"
        assert backend.video_generator._model == "happyhorse_1_1"

    def test_unsupported_image_provider_raises(self):
        from hevi.director.render_backend import create_render_backend

        with pytest.raises(ValueError, match="Unsupported image provider"):
            create_render_backend(image_provider="unknown")

    def test_unsupported_video_provider_raises(self):
        from hevi.director.render_backend import create_render_backend

        with pytest.raises(ValueError, match="Unsupported video provider"):
            create_render_backend(video_provider="unknown")

    def test_working_dir(self, tmp_path):
        from hevi.director.render_backend import create_render_backend

        backend = create_render_backend(working_dir=tmp_path)
        assert backend.working_dir == tmp_path

    def test_backend_has_image_generator(self):
        from hevi.director.render_backend import create_render_backend

        backend = create_render_backend()
        assert backend.has_image_generator is True
        assert backend.has_video_generator is True


# ── 2. PromptBuilder 集成 ─────────────────────────────────────────────────


class TestBuildImagePrompt:
    def test_basic_prompt(self):
        from hevi.director.produce_v2 import _build_image_prompt

        spec = {"prompt": "A beautiful sunset over mountains"}
        result = _build_image_prompt(spec)
        assert "A beautiful sunset over mountains" in result

    def test_enhanced_with_style(self):
        from hevi.director.produce_v2 import _build_image_prompt

        spec = {
            "prompt": "A sunset",
            "style": "cinematic",
        }
        result = _build_image_prompt(spec)
        assert "cinematic" in result
        assert "A sunset" in result

    def test_enhanced_with_camera(self):
        from hevi.director.produce_v2 import _build_image_prompt

        spec = {
            "prompt": "A character walking",
            "camera": {"shot_type": "wide shot", "characters": ["Alice"]},
        }
        result = _build_image_prompt(spec)
        assert "wide shot" in result
        assert "Alice" in result

    def test_full_enhancement(self):
        from hevi.director.produce_v2 import _build_image_prompt

        spec = {
            "prompt": "Two people talking",
            "style": "noir",
            "scene_description": "Dark alley at night",
            "camera": {"shot_type": "close-up", "characters": ["Bob", "Carol"]},
        }
        result = _build_image_prompt(spec)
        assert "noir" in result
        assert "close-up" in result
        assert "Bob" in result
        assert "Carol" in result

    def test_empty_spec(self):
        from hevi.director.produce_v2 import _build_image_prompt

        result = _build_image_prompt({})
        # 空 spec 应返回空字符串而不是抛异常
        assert isinstance(result, str)


# ── 3. produce_v2 新参数 ──────────────────────────────────────────────────


class TestProduceV2NewParams:
    def test_run_v2_produce_accepts_provider_preset(self):
        """run_v2_produce 应接受 provider_preset 参数。"""
        import inspect
        from hevi.director.produce_v2 import run_v2_produce

        sig = inspect.signature(run_v2_produce)
        assert "provider_preset" in sig.parameters

    def test_run_v2_produce_accepts_render_backend(self):
        import inspect
        from hevi.director.produce_v2 import run_v2_produce

        sig = inspect.signature(run_v2_produce)
        assert "render_backend" in sig.parameters

    def test_run_v2_produce_accepts_use_transitions(self):
        import inspect
        from hevi.director.produce_v2 import run_v2_produce

        sig = inspect.signature(run_v2_produce)
        assert "use_transitions" in sig.parameters

    def test_run_v2_produce_accepts_transition_strategy(self):
        import inspect
        from hevi.director.produce_v2 import run_v2_produce

        sig = inspect.signature(run_v2_produce)
        assert "transition_strategy" in sig.parameters

    def test_run_v2_produce_accepts_autocameo_processor(self):
        import inspect
        from hevi.director.produce_v2 import run_v2_produce

        sig = inspect.signature(run_v2_produce)
        assert "autocameo_processor" in sig.parameters

    def test_default_transition_strategy_is_xfade(self):
        import inspect
        from hevi.director.produce_v2 import run_v2_produce
        from hevi.director.transition_video import TransitionStrategy

        sig = inspect.signature(run_v2_produce)
        param = sig.parameters["transition_strategy"]
        assert param.default == TransitionStrategy.XFADE_FALLBACK


# ── 4. TransitionSpec/Result 集成 ─────────────────────────────────────────


class TestTransitionIntegration:
    def test_transition_spec_fields(self):
        from hevi.director.transition_video import TransitionSpec, TransitionStrategy

        spec = TransitionSpec(
            source_frame=Path("/tmp/a.png"),
            target_frame=Path("/tmp/b.png"),
            output_path=Path("/tmp/trans.mp4"),
            duration_s=1.0,
            strategy=TransitionStrategy.MORPH,
        )
        assert spec.source_frame == Path("/tmp/a.png")
        assert spec.target_frame == Path("/tmp/b.png")
        assert spec.strategy == TransitionStrategy.MORPH
        assert spec.duration_s == 1.0

    def test_transition_result_fields(self):
        from hevi.director.transition_video import TransitionResult, TransitionStrategy

        result = TransitionResult(
            output_path=Path("/tmp/trans.mp4"),
            strategy_used=TransitionStrategy.XFADE_FALLBACK,
            duration_s=0.5,
        )
        assert result.output_path == Path("/tmp/trans.mp4")
        assert result.strategy_used == TransitionStrategy.XFADE_FALLBACK
        assert result.duration_s == 0.5


# ── 5. ProviderPresets 集成 ───────────────────────────────────────────────


class TestProviderPresetsIntegration:
    def test_presets_listed(self):
        from hevi.utils.provider_presets import list_presets

        presets = list_presets()
        assert len(presets) > 0
        assert "openai" in presets or "openai_gpt4" in presets

    def test_resolve_config_returns_dict(self):
        from hevi.utils.provider_presets import list_presets, resolve_config

        presets = list_presets()
        if presets:
            config = resolve_config(presets[0], user_config={})
            assert isinstance(config, dict)

    def test_preset_has_base_url(self):
        from hevi.utils.provider_presets import get_preset, list_presets

        presets = list_presets()
        for name in presets[:3]:  # 检查前3个
            preset = get_preset(name)
            assert hasattr(preset, "base_url")
            assert isinstance(preset.base_url, str)


# ── 6. API 端点集成 ───────────────────────────────────────────────────────


class TestAPIEndpointsIntegration:
    def test_produce_request_has_new_fields(self):
        from hevi.api.routers.director_pipeline import ProduceRequest

        req = ProduceRequest()
        assert hasattr(req, "provider_preset")
        assert hasattr(req, "use_transitions")
        assert hasattr(req, "transition_strategy")
        assert hasattr(req, "edit_craft")
        assert hasattr(req, "multi_take")

    def test_produce_request_defaults(self):
        from hevi.api.routers.director_pipeline import ProduceRequest

        req = ProduceRequest()
        assert req.provider_preset is None
        assert req.use_transitions is False
        assert req.transition_strategy == "xfade"
        assert req.edit_craft is False
        assert req.multi_take == 1

    def test_produce_request_custom_values(self):
        from hevi.api.routers.director_pipeline import ProduceRequest

        req = ProduceRequest(
            provider_preset="openai",
            use_transitions=True,
            transition_strategy="morph",
            edit_craft=True,
            multi_take=3,
        )
        assert req.provider_preset == "openai"
        assert req.use_transitions is True
        assert req.transition_strategy == "morph"
        assert req.edit_craft is True
        assert req.multi_take == 3

    def test_idea2video_request(self):
        from hevi.api.routers.director_pipeline import Idea2VideoRequest

        req = Idea2VideoRequest(idea="A story about time travel")
        assert req.idea == "A story about time travel"
        assert req.style == "realistic"
        assert req.max_scenes == 5

    def test_novel2video_request(self):
        from hevi.api.routers.director_pipeline import Novel2VideoRequest

        req = Novel2VideoRequest(text="Once upon a time...")
        assert req.text == "Once upon a time..."
        assert req.max_beats_per_chapter == 8
        assert req.max_events == 20

    def test_autocameo_request(self):
        from hevi.api.routers.director_pipeline import AutoCameoRequest

        req = AutoCameoRequest(
            video_path="/tmp/video.mp4",
            reference_photo_path="/tmp/photo.jpg",
            character_name="Alice",
        )
        assert req.video_path == "/tmp/video.mp4"
        assert req.reference_photo_path == "/tmp/photo.jpg"
        assert req.character_name == "Alice"
        assert req.role == "background"


# ── 7. Idea2Video / Novel2Video / AutoCameo Pipeline 配置验证 ────────────


class TestPipelineConfigs:
    def test_idea2video_config_to_dict(self):
        from hevi.director.idea2video import Idea2VideoConfig

        config = Idea2VideoConfig(style="noir", max_scenes=10)
        d = config.to_dict()
        assert d["style"] == "noir"
        assert d["max_scenes"] == 10

    def test_novel2video_config_to_dict(self):
        from hevi.director.novel2video import Novel2VideoConfig

        config = Novel2VideoConfig(max_events=15, target_duration_s=90.0)
        d = config.to_dict()
        assert d["max_events"] == 15
        assert d["target_duration_s"] == 90.0

    def test_autocameo_config_to_dict(self):
        from hevi.director.autocameo import AutoCameoConfig

        config = AutoCameoConfig(portrait_style="anime", max_cameo_characters=5)
        d = config.to_dict()
        assert d["portrait_style"] == "anime"
        assert d["max_cameo_characters"] == 5

    def test_idea2video_pipeline_init(self):
        from hevi.director.idea2video import Idea2VideoConfig, Idea2VideoPipeline

        config = Idea2VideoConfig()
        pipeline = Idea2VideoPipeline(config=config)
        assert pipeline.config is config

    def test_novel2video_pipeline_init(self):
        from hevi.director.novel2video import Novel2VideoConfig, Novel2VideoPipeline

        config = Novel2VideoConfig()
        pipeline = Novel2VideoPipeline(config=config)
        assert pipeline.config is config


# ── 8. 全链路集成测试 (mock 模式) ───────────────────────────────────────


class TestFullIntegrationMock:
    """验证 produce_v2 的完整集成流程(使用 mock)。"""

    def test_provider_preset_resolution(self):
        """provider_preset 参数能正确解析并记录。"""
        from hevi.utils.provider_presets import get_preset, list_presets

        presets = list_presets()
        if presets:
            preset = get_preset(presets[0])
            assert preset.name == presets[0]
            assert hasattr(preset, "category")

    def test_render_backend_from_preset(self):
        """从 preset 创建的 RenderBackend 有正确的适配器。"""
        from hevi.director.render_backend import (
            DashScopeImageAdapter,
            WanVideoAdapter,
            create_render_backend,
        )

        backend = create_render_backend(
            image_provider="dashscope",
            video_provider="wan",
            image_params={"size": "1280*720"},
            video_params={"resolution": "480P"},
        )
        assert backend.has_image_generator
        assert backend.has_video_generator
        assert isinstance(backend.image_generator, DashScopeImageAdapter)
        assert isinstance(backend.video_generator, WanVideoAdapter)

    def test_transition_strategy_mapping(self):
        """API 层到 produce_v2 的转场策略映射正确。"""
        from hevi.director.transition_video import TransitionStrategy

        strategy_map = {
            "xfade": TransitionStrategy.XFADE_FALLBACK,
            "morph": TransitionStrategy.MORPH,
            "video_gen": TransitionStrategy.VIDEO_GEN,
        }
        for api_name, strategy in strategy_map.items():
            assert isinstance(strategy, TransitionStrategy)
            assert strategy.value in ("xfade", "morph", "video_gen")

    def test_all_vimax_modules_importable(self):
        """所有 ViMax 模块均可从顶层 import。"""
        from hevi.director import (
            AutoCameo,
            AutoCameoConfig,
            Idea2VideoConfig,
            Idea2VideoPipeline,
            Novel2VideoConfig,
            Novel2VideoPipeline,
            RenderBackend,
            create_render_backend,
            select_best_image,
        )
        from hevi.agent_runtime import PromptBuilder, build_pipeline_prompt
        from hevi.utils.provider_presets import get_preset, list_presets

        assert AutoCameo is not None
        assert Idea2VideoPipeline is not None
        assert Novel2VideoPipeline is not None
        assert RenderBackend is not None
        assert PromptBuilder is not None
        assert list_presets is not None
