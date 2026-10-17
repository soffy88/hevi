"""HyperFrames 能力测试 — 6 项能力全测试。

测试覆盖:
  - hyperframes_service: HTML composition 构建 (~4 tests)
  - animation: GSAP timeline builder (~8 tests)
  - blocks: Block 组件目录 (~6 tests)
  - transitions: Shader 转场 (~2 tests)
  - media: Media OS (~6 tests)
  - design: Frame.md 设计系统 (~6 tests)

运行: .venv/bin/python -m pytest tests/test_hyperframes_features.py --noconftest -v
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HyperFrames Service tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.hyperframes_service import (
    build_html_composition,
    HyperFramesRenderResult,
)


class TestBuildHtmlComposition:
    @pytest.mark.asyncio
    async def test_basic_composition(self, tmp_path):
        html = await build_html_composition(
            "<h1>Test</h1>",
            tmp_path,
            width=1920,
            height=1080,
        )
        assert html.exists()
        content = html.read_text()
        assert "data-composition-id" in content
        assert "<h1>Test</h1>" in content

    @pytest.mark.asyncio
    async def test_custom_composition_id(self, tmp_path):
        html = await build_html_composition(
            "<div>Content</div>",
            tmp_path,
            composition_id="my-comp",
        )
        content = html.read_text()
        assert 'id="my-comp"' in content
        assert 'data-composition-id="my-comp"' in content

    @pytest.mark.asyncio
    async def test_dimensions_in_output(self, tmp_path):
        html = await build_html_composition(
            "<p>Text</p>",
            tmp_path,
            width=1280,
            height=720,
        )
        content = html.read_text()
        assert "1280" in content
        assert "720" in content


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Animation tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.animation import (
    GsapTimelineBuilder,
    AnimationEase,
    build_gsap_script,
)


class TestGsapTimelineBuilder:
    def test_empty_timeline(self):
        builder = GsapTimelineBuilder()
        script = builder.build()
        assert "gsap.timeline" in script
        assert "paused: true" in script

    def test_from_element(self):
        builder = GsapTimelineBuilder()
        builder.from_element(".title", opacity=0, y=-50, duration=1.0)
        script = builder.build()
        assert '.from(".title"' in script
        assert '"opacity": 0' in script

    def test_to_element(self):
        builder = GsapTimelineBuilder()
        builder.to_element(".subtitle", opacity=1, duration=0.5)
        script = builder.build()
        assert '.to(".subtitle"' in script

    def test_set_element(self):
        builder = GsapTimelineBuilder()
        builder.set_element(".bg", opacity=1)
        script = builder.build()
        assert '.set(".bg"' in script

    def test_chained_steps(self):
        builder = GsapTimelineBuilder()
        builder.from_element(".title", opacity=0, duration=1.0)
        builder.to_element(".title", y=0, duration=0.5)
        script = builder.build()
        assert script.count(".from") == 1
        assert script.count(".to") == 1

    def test_timeline_registered(self):
        builder = GsapTimelineBuilder()
        script = builder.build()
        assert "window.__timelines" in script

    def test_ease_constants(self):
        assert AnimationEase.LINEAR == "none"
        assert AnimationEase.EASE_OUT == "power2.out"
        assert AnimationEase.ELASTIC == "elastic.out(1, 0.3)"


class TestBuildGsapScript:
    def test_convenience_function(self):
        builder = GsapTimelineBuilder()
        builder.from_element(".test", opacity=0)
        script = build_gsap_script(builder)
        assert "gsap.timeline" in script


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Blocks tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.blocks import get_block, list_blocks, BLOCKS


class TestBlocks:
    def test_list_blocks(self):
        blocks = list_blocks()
        assert "title_card" in blocks
        assert "subtitle" in blocks
        assert len(blocks) >= 5

    def test_get_title_card(self):
        html = get_block("title_card", title="第一章", subtitle="秦统一中国")
        assert "第一章" in html
        assert "秦统一中国" in html
        assert "title-card" in html

    def test_get_subtitle(self):
        html = get_block("subtitle", text="讲解内容", position="bottom")
        assert "讲解内容" in html
        assert "position_style" in html or "bottom" in html

    def test_get_lower_third(self):
        html = get_block("lower_third", name="张三", title="CEO", accent_color="#FF0000")
        assert "张三" in html
        assert "CEO" in html
        assert "#FF0000" in html

    def test_get_kinetic_text(self):
        html = get_block("kinetic_text", text="关键数据")
        assert "关键数据" in html

    def test_get_quote(self):
        html = get_block("quote", text="名言警句", author="孔子")
        assert "名言警句" in html
        assert "孔子" in html

    def test_unknown_block_raises(self):
        with pytest.raises(ValueError, match="Unknown block"):
            get_block("nonexistent_block")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Transitions tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.video.transitions import TRANSITION_PRESETS, TransitionType


class TestTransitions:
    def test_presets_exist(self):
        assert "crossfade" in TRANSITION_PRESETS
        assert "fade_black" in TRANSITION_PRESETS
        assert len(TRANSITION_PRESETS) >= 5

    def test_preset_values(self):
        assert TRANSITION_PRESETS["crossfade"] == "fade"
        assert TRANSITION_PRESETS["fade_black"] == "fadeblack"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Media OS tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.media import MediaRegistry, MediaAsset, MediaCategory


class TestMediaRegistry:
    def test_register_asset(self, tmp_path):
        registry = MediaRegistry()
        asset_file = tmp_path / "test.mp3"
        asset_file.write_text("mock")

        asset = registry.register("bgm_1", asset_file, category=MediaCategory.AUDIO)
        assert asset.id == "bgm_1"
        assert asset.category == "audio"

    def test_resolve_asset(self, tmp_path):
        registry = MediaRegistry()
        asset_file = tmp_path / "logo.png"
        asset_file.write_text("mock")

        registry.register("logo", asset_file, category=MediaCategory.IMAGE)
        resolved = registry.resolve("logo")
        assert resolved is not None
        assert resolved.id == "logo"

    def test_list_by_category(self, tmp_path):
        registry = MediaRegistry()
        f1 = tmp_path / "a.mp3"
        f2 = tmp_path / "b.mp3"
        f3 = tmp_path / "c.png"
        for f in [f1, f2, f3]:
            f.write_text("mock")

        registry.register("a", f1, category="audio")
        registry.register("b", f2, category="audio")
        registry.register("c", f3, category="image")

        audio = registry.list(category="audio")
        assert len(audio) == 2

    def test_unregister(self, tmp_path):
        registry = MediaRegistry()
        f = tmp_path / "test.mp3"
        f.write_text("mock")

        registry.register("test", f)
        assert "test" in registry
        registry.unregister("test")
        assert "test" not in registry

    def test_save_and_load_manifest(self, tmp_path):
        registry = MediaRegistry()
        f = tmp_path / "asset.mp3"
        f.write_text("mock")

        registry.register("asset_1", f, category="audio", name="Test BGM")

        manifest_path = tmp_path / "manifest.json"
        registry.save_manifest(manifest_path)

        # Load into new registry
        registry2 = MediaRegistry()
        registry2.load_manifest(manifest_path)
        assert "asset_1" in registry2
        assert registry2.resolve("asset_1").name == "Test BGM"


class TestMediaAsset:
    def test_to_dict(self, tmp_path):
        asset = MediaAsset(
            id="test",
            path=tmp_path / "file.mp3",
            category="audio",
            name="Test",
        )
        d = asset.to_dict()
        assert d["id"] == "test"
        assert "file.mp3" in d["path"]

    def test_from_dict(self, tmp_path):
        d = {
            "id": "test",
            "path": str(tmp_path / "file.mp3"),
            "category": "audio",
            "name": "Test",
        }
        asset = MediaAsset.from_dict(d)
        assert asset.id == "test"
        assert isinstance(asset.path, Path)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Design System tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from hevi.design import DesignSystem, load_design, DEFAULT_DESIGN


class TestDesignSystem:
    def test_get_nested_token(self):
        ds = DesignSystem()
        assert ds.get("typography.title.size") == 72
        assert ds.get("colors.primary") == "#4F46E5"
        assert ds.get("spacing.lg") == 32

    def test_get_missing_returns_default(self):
        ds = DesignSystem()
        assert ds.get("nonexistent.key") is None
        assert ds.get("nonexistent.key", "fallback") == "fallback"

    def test_set_token(self):
        ds = DesignSystem()
        ds.set("colors.primary", "#FF0000")
        assert ds.get("colors.primary") == "#FF0000"

    def test_to_css_variables(self):
        ds = DesignSystem({"typography": {"title": {"size": 72}}})
        css = ds.to_css_variables()
        assert ":root {" in css
        assert "--typography-title-size: 72px;" in css

    def test_save_json(self, tmp_path):
        ds = DesignSystem()
        output = tmp_path / "design.json"
        ds.save(output)
        assert output.exists()

    def test_default_design_has_all_sections(self):
        ds = DesignSystem()
        assert ds.get("typography") is not None
        assert ds.get("colors") is not None
        assert ds.get("spacing") is not None
        assert ds.get("animation") is not None
        assert ds.get("layout") is not None


class TestLoadDesign:
    def test_load_nonexistent_returns_default(self, tmp_path):
        ds = load_design(tmp_path / "nonexistent.yaml")
        assert ds.get("typography.title.size") == 72

    def test_load_json(self, tmp_path):
        import json
        design_file = tmp_path / "design.json"
        design_file.write_text(json.dumps({"colors": {"primary": "#00FF00"}}))
        ds = load_design(design_file)
        assert ds.get("colors.primary") == "#00FF00"
