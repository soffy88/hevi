"""額外功能測試 —— 驗證新實現的功能."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestMathAnimation:
    def test_import(self):
        from hevi.math_animation import create_math_animation, create_sample_math_script
        assert callable(create_math_animation)
        assert callable(create_sample_math_script)

    def test_create_sample_script(self):
        from hevi.math_animation import create_sample_math_script
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            script_path = Path(f.name)
        
        result = create_sample_math_script(script_path, "Test Animation")
        assert result.exists()
        content = result.read_text()
        assert "MathAnimation" in content
        assert "E = mc^2" in content
        result.unlink()  # 清理


class TestCharacterAnimation:
    def test_import(self):
        from hevi.character_animation import CharacterAnimator, CharacterRig, Joint, BodyPart, PoseFrame
        assert CharacterAnimator
        assert CharacterRig
        assert Joint
        assert BodyPart
        assert PoseFrame

    def test_create_animator(self):
        from hevi.character_animation import CharacterAnimator
        animator = CharacterAnimator()
        assert animator.rigs == {}

    def test_create_character_rig(self):
        import asyncio
        from hevi.character_animation import CharacterAnimator
        
        async def _test():
            animator = CharacterAnimator()
            svg_path = await animator.create_character_rig(
                name="test_char",
                body_parts=["head", "torso", "arm_left", "arm_right", "leg_left", "leg_right"]
            )
            assert svg_path.exists()
            content = svg_path.read_text()
            assert "<svg" in content
            assert "character" in content
            return svg_path
        
        svg_path = asyncio.run(_test())
        # 清理
        if svg_path and svg_path.exists():
            svg_path.unlink()


class TestHyperFramesService:
    def test_import(self):
        from hevi.video.hyperframes_service import render_hyperframes, list_hyperframes_presets
        assert callable(render_hyperframes)
        assert callable(list_hyperframes_presets)

    def test_list_presets(self):
        import asyncio
        from hevi.video.hyperframes_service import list_hyperframes_presets
        
        async def _test():
            presets = await list_hyperframes_presets()
            assert len(presets) >= 1
            ids = [p["id"] for p in presets]
            assert "basic" in ids
            return presets
        
        presets = asyncio.run(_test())
        assert len(presets) >= 1


class TestAgentSkills:
    def test_import(self):
        from hevi.agent_skills import SkillManager, Skill, get_skill_manager, get_predefined_skill
        assert SkillManager
        assert Skill
        assert callable(get_skill_manager)
        assert callable(get_predefined_skill)

    def test_skill_manager_init(self):
        from hevi.agent_skills import SkillManager
        manager = SkillManager()
        assert manager.skills == {}
        assert not manager._loaded

    def test_get_predefined_skills(self):
        import asyncio
        from hevi.agent_skills import get_predefined_skill
        
        async def _test():
            skill = await get_predefined_skill("text-to-speech-guidelines")
            assert skill is not None
            assert skill.id == "text-to-speech-guidelines"
            assert "Text-to-Speech" in skill.title
            assert skill.category == "audio"
            return skill
        
        skill = asyncio.run(_test())
        assert skill is not None


class TestReviewer:
    def test_import(self):
        from hevi.reviewer import PipelineReviewer, ReviewFinding, ReviewReport, ReviewCategory, Severity
        assert PipelineReviewer
        assert ReviewFinding
        assert ReviewReport
        assert ReviewCategory
        assert Severity

    def test_reviewer_init(self):
        from hevi.reviewer import PipelineReviewer
        reviewer = PipelineReviewer()
        assert "research" in reviewer.review_templates
        assert "script" in reviewer.review_templates

    def test_review_stages_available(self):
        from hevi.reviewer import PipelineReviewer
        reviewer = PipelineReviewer()
        available_stages = list(reviewer.review_templates.keys())
        expected_stages = ["research", "script", "scene_plan", "assets", "edit", "compose"]
        for stage in expected_stages:
            assert stage in available_stages

    def test_review_single_stage(self):
        import asyncio
        from hevi.reviewer import PipelineReviewer
        
        async def _test():
            reviewer = PipelineReviewer()
            report = await reviewer.review_stage(
                stage="script",
                content="This is a test script with a beginning and an end.",
                context={"target_duration_minutes": 3}
            )
            assert report.stage == "script"
            assert 0.0 <= report.score <= 1.0
            assert isinstance(report.summary, str)
            assert isinstance(report.findings, list)
            return report
        
        report = asyncio.run(_test())
        assert report.stage == "script"