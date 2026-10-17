"""ViMax Batch 3 能力接入测试。

覆盖：
  - Camera Tree 构建和遍历
  - Transition Video 生成
  - Render Backend Factory
  - Idea2Video Pipeline
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest


# ═══════════════════════════════════════════════════════════════════════
# Camera Tree 测试
# ═══════════════════════════════════════════════════════════════════════


class TestCameraTree:
    """Camera Tree 测试套件。"""

    def test_camera_node_basic(self):
        from hevi.director.camera_tree import CameraNode
        node = CameraNode(cam_idx=0, shot_idxs=[0, 1, 2])
        assert node.cam_idx == 0
        assert node.shot_idxs == [0, 1, 2]
        assert node.is_root
        assert not node.has_parent

    def test_camera_node_with_parent(self):
        from hevi.director.camera_tree import CameraNode
        node = CameraNode(cam_idx=1, shot_idxs=[3, 4], parent_cam_idx=0, parent_shot_idx=2, reason="特写")
        assert node.has_parent
        assert not node.is_root
        assert node.parent_cam_idx == 0

    def test_camera_tree_construction(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1, 2]))
        tree.add(CameraNode(1, [3, 4], parent_cam_idx=0, parent_shot_idx=2))
        tree.add(CameraNode(2, [5, 6], parent_cam_idx=1, parent_shot_idx=4))
        assert len(tree.all_cameras) == 3
        assert len(tree.roots) == 1
        assert tree.roots[0].cam_idx == 0

    def test_camera_tree_generation_order(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        tree = CameraTree()
        tree.add(CameraNode(2, [5, 6], parent_cam_idx=1, parent_shot_idx=4))
        tree.add(CameraNode(0, [0, 1, 2]))
        tree.add(CameraNode(1, [3, 4], parent_cam_idx=0, parent_shot_idx=2))
        order = tree.generation_order()
        assert order.index(0) < order.index(1)
        assert order.index(1) < order.index(2)

    def test_camera_tree_priority_shots(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1, 2]))
        tree.add(CameraNode(1, [3, 4], parent_cam_idx=0, parent_shot_idx=2))
        tree.add(CameraNode(2, [5, 6], parent_cam_idx=1, parent_shot_idx=4))
        priority = tree.get_priority_shots()
        assert 2 in priority
        assert 4 in priority

    def test_camera_tree_serialization(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1], reason="主镜头"))
        tree.add(CameraNode(1, [2, 3], parent_cam_idx=0, parent_shot_idx=1))
        data = tree.to_dict()
        tree2 = CameraTree.from_dict(data)
        assert len(tree2.all_cameras) == 2
        assert tree2.get(0).reason == "主镜头"
        assert tree2.get(1).parent_cam_idx == 0

    def test_construct_camera_tree_from_shots(self):
        from hevi.director.camera_tree import construct_camera_tree
        shots = [
            {"idx": 0, "environment": "forest", "cam_idx": 0},
            {"idx": 1, "environment": "forest", "cam_idx": 0},
            {"idx": 2, "environment": "forest", "cam_idx": 1},
            {"idx": 3, "environment": "castle", "cam_idx": 0},
        ]
        tree = construct_camera_tree(shots)
        assert len(tree.all_cameras) >= 2

    def test_construct_camera_tree_simple(self):
        from hevi.director.camera_tree import construct_camera_tree
        shots = [
            {"idx": 0, "cam_idx": 0},
            {"idx": 1, "cam_idx": 0},
        ]
        tree = construct_camera_tree(shots, spatial_grouping=False)
        assert len(tree.all_cameras) == 2

    def test_camera_tree_validation_ok(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1]))
        tree.add(CameraNode(1, [2, 3], parent_cam_idx=0))
        issues = tree.validate()
        assert len(issues) == 0

    def test_camera_tree_validation_bad_parent(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1]))
        tree.add(CameraNode(1, [2, 3], parent_cam_idx=99))
        issues = tree.validate()
        assert len(issues) > 0
        assert "non-existent parent" in issues[0]

    def test_children_of(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1]))
        tree.add(CameraNode(1, [2], parent_cam_idx=0))
        tree.add(CameraNode(2, [3], parent_cam_idx=0))
        children = tree.children_of(0)
        assert len(children) == 2

    def test_compute_missing_info(self):
        from hevi.director.camera_tree import CameraNode, CameraTree, compute_missing_info
        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1]))
        tree.add(CameraNode(1, [2], parent_cam_idx=0, parent_shot_idx=1))

        shot_descs = {
            0: {"visible_chars": ["Alice"], "environment": "forest"},
            1: {"visible_chars": ["Alice"], "environment": "forest"},
            2: {"visible_chars": ["Alice", "Bob"], "environment": "forest"},
        }
        compute_missing_info(tree, shot_descs)
        child = tree.get(1)
        assert "Bob" in child.missing_info


# ═══════════════════════════════════════════════════════════════════════
# Transition Video 测试
# ═══════════════════════════════════════════════════════════════════════


class TestTransitionVideo:
    """Transition Video 测试套件。"""

    def test_transition_spec_creation(self):
        from hevi.director.transition_video import TransitionSpec, TransitionStrategy
        spec = TransitionSpec(
            source_frame=Path("/tmp/frame_0.png"),
            target_frame=Path("/tmp/frame_1.png"),
            output_path=Path("/tmp/trans.mp4"),
            duration_s=2.0,
            strategy=TransitionStrategy.XFADE_FALLBACK,
        )
        assert spec.duration_s == 2.0
        assert spec.strategy == TransitionStrategy.XFADE_FALLBACK

    def test_transition_strategy_enum(self):
        from hevi.director.transition_video import TransitionStrategy
        assert TransitionStrategy.VIDEO_GEN == "video_gen"
        assert TransitionStrategy.MORPH == "morph"
        assert TransitionStrategy.XFADE_FALLBACK == "xfade"

    def test_transition_result_creation(self):
        from hevi.director.transition_video import TransitionResult, TransitionStrategy
        result = TransitionResult(
            output_path=Path("/tmp/transition.mp4"),
            strategy_used=TransitionStrategy.XFADE_FALLBACK,
            duration_s=2.0,
            fallback_reason="video_gen failed",
        )
        assert result.fallback_reason == "video_gen failed"
        assert result.strategy_used == TransitionStrategy.XFADE_FALLBACK

    def test_transition_result_to_dict(self):
        from hevi.director.transition_video import TransitionResult, TransitionStrategy
        result = TransitionResult(
            output_path=Path("/tmp/t.mp4"),
            strategy_used=TransitionStrategy.MORPH,
            duration_s=1.5,
        )
        d = result.to_dict()
        assert d["strategy_used"] == "morph"
        assert d["duration_s"] == 1.5

    def test_transition_spec_to_dict(self):
        from hevi.director.transition_video import TransitionSpec, TransitionStrategy
        spec = TransitionSpec(
            source_frame=Path("/tmp/a.png"),
            target_frame=Path("/tmp/b.png"),
            output_path=Path("/tmp/t.mp4"),
            duration_s=3.0,
            strategy=TransitionStrategy.MORPH,
            prompt="smooth transition",
        )
        d = spec.to_dict()
        assert d["duration_s"] == 3.0
        assert d["strategy"] == "morph"

    def test_build_transition_prompt(self):
        from hevi.director.transition_video import build_transition_prompt
        prompt = build_transition_prompt(
            source_description="森林远景",
            target_description="城堡特写",
            missing_info="城堡全貌",
            duration_s=2.0,
        )
        assert "森林远景" in prompt
        assert "城堡特写" in prompt
        assert "城堡全貌" in prompt
        assert isinstance(prompt, str)

    def test_build_transition_prompt_no_missing(self):
        from hevi.director.transition_video import build_transition_prompt
        prompt = build_transition_prompt(
            source_description="A",
            target_description="B",
        )
        assert "A" in prompt
        assert "B" in prompt


# ═══════════════════════════════════════════════════════════════════════
# Render Backend Factory 测试
# ═══════════════════════════════════════════════════════════════════════


class TestRenderBackendFactory:
    """Render Backend Factory 测试套件。"""

    def test_render_backend_config_basic(self):
        from hevi.director.render_backend import RenderBackendConfig
        config = RenderBackendConfig(
            image_generator={"class_path": "some.module.func"},
            video_generator={"class_path": "some.module.func2"},
            working_dir="/tmp/work",
        )
        assert config.image_generator is not None
        assert config.working_dir == "/tmp/work"

    def test_render_backend_config_to_dict(self):
        from hevi.director.render_backend import RenderBackendConfig
        config = RenderBackendConfig(
            image_generator={"class_path": "x"},
            working_dir="/tmp",
        )
        d = config.to_dict()
        assert d["image_generator"]["class_path"] == "x"

    def test_render_backend_from_config_none(self):
        from hevi.director.render_backend import RenderBackend
        backend = RenderBackend.from_config({})
        assert not backend.has_image_generator
        assert not backend.has_video_generator

    def test_render_backend_from_config_missing(self):
        from hevi.director.render_backend import RenderBackend
        backend = RenderBackend.from_config({
            "image_generator": {"class_path": "nonexistent.module.func"},
        })
        assert not backend.has_image_generator

    def test_render_backend_from_config_object(self):
        from hevi.director.render_backend import RenderBackend, RenderBackendConfig
        config = RenderBackendConfig(
            image_generator={"class_path": "nonexistent.x.y"},
        )
        backend = RenderBackend.from_config(config)
        assert not backend.has_image_generator

    def test_import_callable_module(self):
        from hevi.director.render_backend import _import_callable
        fn = _import_callable("json.loads")
        assert callable(fn)
        result = fn('{"a": 1}')
        assert result == {"a": 1}

    def test_import_callable_nested(self):
        from hevi.director.render_backend import _import_callable
        fn = _import_callable("pathlib.Path.exists")
        assert callable(fn)

    def test_import_callable_invalid(self):
        from hevi.director.render_backend import _import_callable
        with pytest.raises(ImportError):
            _import_callable("nope")

    def test_function_image_generator(self):
        from hevi.director.render_backend import FunctionImageGenerator

        async def mock_gen(prompt, reference_images, output_path, **kw):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"img")
            return output_path

        gen = FunctionImageGenerator(mock_gen, {"quality": "high"})

        loop = asyncio.new_event_loop()
        try:
            with tempfile.TemporaryDirectory() as td:
                result = loop.run_until_complete(
                    gen.generate("test", [], Path(td) / "out.png")
                )
                assert result.exists()
        finally:
            loop.close()

    def test_function_video_generator(self):
        from hevi.director.render_backend import FunctionVideoGenerator

        async def mock_gen(prompt, reference_images, output_path, **kw):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"vid")
            return output_path

        gen = FunctionVideoGenerator(mock_gen)

        loop = asyncio.new_event_loop()
        try:
            with tempfile.TemporaryDirectory() as td:
                result = loop.run_until_complete(
                    gen.generate("test", [], Path(td) / "out.mp4")
                )
                assert result.exists()
        finally:
            loop.close()

    def test_render_backend_generate_no_generator(self):
        from hevi.director.render_backend import RenderBackend
        backend = RenderBackend()

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="no image generator"):
                loop.run_until_complete(backend.generate_image("test"))
        finally:
            loop.close()

    def test_list_presets(self):
        from hevi.director.render_backend import list_presets
        presets = list_presets()
        assert isinstance(presets, list)
        assert "minimax" in presets

    def test_create_backend_from_invalid_preset(self):
        from hevi.director.render_backend import create_backend_from_preset
        with pytest.raises(ValueError, match="unknown preset"):
            create_backend_from_preset("nonexistent")


# ═══════════════════════════════════════════════════════════════════════
# Idea2Video Pipeline 测试
# ═══════════════════════════════════════════════════════════════════════


class TestIdea2VideoPipeline:
    """Idea2Video Pipeline 测试套件。"""

    def test_idea2video_config(self):
        from hevi.director.idea2video import Idea2VideoConfig
        config = Idea2VideoConfig(max_scenes=5, fps=24, resolution="720p", style="realistic")
        assert config.max_scenes == 5
        assert config.fps == 24

    def test_idea2video_config_to_dict(self):
        from hevi.director.idea2video import Idea2VideoConfig
        config = Idea2VideoConfig(max_scenes=3)
        d = config.to_dict()
        assert d["max_scenes"] == 3
        assert d["fps"] == 24

    def test_idea2video_result(self):
        from hevi.director.idea2video import Idea2VideoResult
        result = Idea2VideoResult(
            final_video_path=Path("/tmp/final.mp4"),
            story_text="测试故事",
            characters=[{"name": "角色A"}],
            duration_s=30.0,
        )
        assert result.duration_s == 30.0
        assert result.story_text == "测试故事"

    def test_idea2video_result_to_dict(self):
        from hevi.director.idea2video import Idea2VideoResult
        result = Idea2VideoResult(final_video_path=Path("/tmp/f.mp4"), duration_s=10.0)
        d = result.to_dict()
        assert d["duration_s"] == 10.0

    def test_develop_story_no_llm(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        pipeline = Idea2VideoPipeline(config=Idea2VideoConfig())
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                pipeline._develop_story("猫和狗的故事", "")
            )
            assert "story_text" in result
            assert result["story_text"] == "猫和狗的故事"
        finally:
            loop.close()

    def test_extract_characters_no_llm(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        pipeline = Idea2VideoPipeline(config=Idea2VideoConfig())
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                pipeline._extract_characters("小花和大黄在森林玩耍")
            )
            assert "characters" in result
        finally:
            loop.close()

    def test_write_script_no_llm(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        pipeline = Idea2VideoPipeline(config=Idea2VideoConfig(max_scenes=2))
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                pipeline._write_script("小花和大黄的故事", "")
            )
            assert "scenes" in result
            assert len(result["scenes"]) >= 1
        finally:
            loop.close()

    def test_design_storyboard_no_llm(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        pipeline = Idea2VideoPipeline(config=Idea2VideoConfig())
        scenes = [{"slugline": "EXT. FOREST", "script": "test"}]
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                pipeline._design_storyboard(scenes, [], "")
            )
            assert "shots" in result
            assert len(result["shots"]) >= 1
        finally:
            loop.close()

    def test_construct_camera_tree_stage(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        pipeline = Idea2VideoPipeline(config=Idea2VideoConfig())
        shots = [{"idx": 0, "cam_idx": 0}, {"idx": 1, "cam_idx": 0}]
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(pipeline._construct_camera_tree(shots))
            assert "tree" in result
        finally:
            loop.close()

    def test_generate_shots_no_gen(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        with tempfile.TemporaryDirectory() as td:
            pipeline = Idea2VideoPipeline(config=Idea2VideoConfig(working_dir=Path(td)))
            shots = [{"idx": 0, "visual_desc": "test"}]
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    pipeline._generate_shots(shots, {})
                )
                assert "shot_paths" in result
                assert len(result["shot_paths"]) == 1
            finally:
                loop.close()

    def test_assemble_final_empty(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        with tempfile.TemporaryDirectory() as td:
            pipeline = Idea2VideoPipeline(config=Idea2VideoConfig(working_dir=Path(td)))
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(pipeline._assemble_final([]))
                assert "output_path" in result
                assert result["duration_s"] == 0.0
            finally:
                loop.close()

    def test_full_pipeline_no_llm(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        with tempfile.TemporaryDirectory() as td:
            pipeline = Idea2VideoPipeline(
                config=Idea2VideoConfig(working_dir=Path(td), max_scenes=1)
            )
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    pipeline.run("一只猫的故事", style="cartoon")
                )
                assert isinstance(result.final_video_path, Path)
                assert result.story_text is not None
            finally:
                loop.close()

    def test_init_from_config_missing_file(self):
        from hevi.director.idea2video import Idea2VideoPipeline
        pipeline = Idea2VideoPipeline.init_from_config("/nonexistent/config.yaml")
        assert pipeline.config.max_scenes == 5

    def test_stages_list(self):
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig
        pipeline = Idea2VideoPipeline(config=Idea2VideoConfig())
        stages = pipeline._stages()
        assert "develop_story" in stages
        assert "assemble_final" in stages
        assert len(stages) == 8


# ═══════════════════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════════════════


class TestViMaxBatch3Integration:
    """ViMax Batch 3 集成测试。"""

    def test_camera_tree_with_transition(self):
        from hevi.director.camera_tree import CameraNode, CameraTree
        from hevi.director.transition_video import TransitionSpec, TransitionStrategy

        tree = CameraTree()
        tree.add(CameraNode(0, [0, 1, 2]))
        tree.add(CameraNode(1, [3, 4], parent_cam_idx=0, parent_shot_idx=2))

        child = tree.get(1)
        assert child.has_parent
        spec = TransitionSpec(
            source_frame=Path("/tmp/frame_2.png"),
            target_frame=Path("/tmp/frame_3.png"),
            output_path=Path("/tmp/trans.mp4"),
            duration_s=2.0,
            strategy=TransitionStrategy.XFADE_FALLBACK,
        )
        assert spec.duration_s == 2.0

    def test_render_backend_with_idea2video(self):
        from hevi.director.render_backend import RenderBackend
        from hevi.director.idea2video import Idea2VideoConfig

        backend = RenderBackend()
        assert not backend.has_video_generator

        config = Idea2VideoConfig()
        assert config.resolution == "720p"

    def test_all_imports(self):
        from hevi.director import (
            CameraNode,
            CameraTree,
            construct_camera_tree,
            TransitionResult,
            TransitionSpec,
            TransitionStrategy,
            bridge_shots,
            generate_transition_video,
            RenderBackend,
            RenderBackendConfig,
            Idea2VideoConfig,
            Idea2VideoPipeline,
            Idea2VideoResult,
        )
        assert CameraNode is not None
        assert RenderBackend is not None
        assert Idea2VideoPipeline is not None

    def test_pipeline_with_checkpoint(self):
        """Idea2Video + checkpoint 集成。"""
        from hevi.director.idea2video import Idea2VideoPipeline, Idea2VideoConfig

        with tempfile.TemporaryDirectory() as td:
            pipeline = Idea2VideoPipeline(config=Idea2VideoConfig(working_dir=Path(td)))

            loop = asyncio.new_event_loop()
            try:
                r1 = loop.run_until_complete(pipeline.run("test idea"))
                assert r1.story_text == "test idea"

                # 第二次运行应该使用 checkpoint
                r2 = loop.run_until_complete(pipeline.run("test idea"))
                assert r2.story_text == "test idea"
            finally:
                loop.close()
