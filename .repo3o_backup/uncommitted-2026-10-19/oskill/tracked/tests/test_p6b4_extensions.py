"""Tests for P6-B4: script_writer template_prompt + storyboard_planner motion field."""

from __future__ import annotations

import json
from typing import Any

from oskill._schemas import Script

# ═══════════════════════════════════════════════════════════════════════════════
# script_writer — template_prompt extension
# ═══════════════════════════════════════════════════════════════════════════════


class TestScriptWriterTemplatePrompt:
    def _make_llm(self, title: str = "Test") -> Any:
        resp = json.dumps(
            {
                "title": title,
                "description": "d",
                "scenes": [
                    {"index": 0, "narration": "n", "duration_s": 5.0, "visual_description": "v"}
                ],
                "estimated_duration_s": 5.0,
            }
        )
        return lambda **kw: {"content": resp}

    async def test_template_prompt_injected_as_system(self) -> None:
        from oskill.script_writer import script_writer

        calls: list[dict[str, Any]] = []

        def _llm(**kw: Any) -> dict[str, Any]:
            calls.append(kw)
            return {
                "content": json.dumps(
                    {
                        "title": "T",
                        "description": "d",
                        "scenes": [
                            {
                                "index": 0,
                                "narration": "n",
                                "duration_s": 5.0,
                                "visual_description": "v",
                            }
                        ],
                        "estimated_duration_s": 5.0,
                    }
                )
            }

        await script_writer(
            topic="test",
            target_duration_s=60,
            llm=_llm,
            template_prompt="You are a quant finance expert. Generate {topic} content.",
        )
        system_msg = calls[0]["messages"][0]["content"]
        assert "quant finance expert" in system_msg

    async def test_template_prompt_none_uses_default(self) -> None:
        from oskill.script_writer import script_writer

        calls: list[dict[str, Any]] = []

        def _llm(**kw: Any) -> dict[str, Any]:
            calls.append(kw)
            return {
                "content": json.dumps(
                    {
                        "title": "T",
                        "description": "d",
                        "scenes": [
                            {
                                "index": 0,
                                "narration": "n",
                                "duration_s": 5.0,
                                "visual_description": "v",
                            }
                        ],
                        "estimated_duration_s": 5.0,
                    }
                )
            }

        await script_writer(topic="test", target_duration_s=60, llm=_llm)
        system_msg = calls[0]["messages"][0]["content"]
        assert "video script writer" in system_msg

    async def test_different_templates_produce_different_prompts(self) -> None:
        from oskill.script_writer import script_writer

        calls: list[dict[str, Any]] = []

        def _llm(**kw: Any) -> dict[str, Any]:
            calls.append(kw)
            return {
                "content": json.dumps(
                    {
                        "title": "T",
                        "description": "d",
                        "scenes": [
                            {
                                "index": 0,
                                "narration": "n",
                                "duration_s": 5.0,
                                "visual_description": "v",
                            }
                        ],
                        "estimated_duration_s": 5.0,
                    }
                )
            }

        await script_writer(
            topic="t",
            target_duration_s=60,
            llm=_llm,
            template_prompt="TEMPLATE_A",
        )
        await script_writer(
            topic="t",
            target_duration_s=60,
            llm=_llm,
            template_prompt="TEMPLATE_B",
        )
        assert calls[0]["messages"][0]["content"] == "TEMPLATE_A"
        assert calls[1]["messages"][0]["content"] == "TEMPLATE_B"

    async def test_backward_compat_no_template(self) -> None:
        from oskill.script_writer import script_writer

        result = await script_writer(
            topic="cats",
            target_duration_s=30,
            llm=self._make_llm(),
        )
        assert isinstance(result, Script)
        assert result.title == "Test"


# ═══════════════════════════════════════════════════════════════════════════════
# storyboard_planner — motion field extension
# ═══════════════════════════════════════════════════════════════════════════════


class TestStoryboardPlannerMotion:
    def _script(self) -> Script:
        return Script(
            title="T",
            description="d",
            scenes=[{"index": 0, "narration": "n", "duration_s": 5.0, "visual_description": "v"}],
            estimated_duration_s=5.0,
        )

    async def test_motion_field_parsed(self) -> None:
        from oskill.storyboard_planner import storyboard_planner

        resp = json.dumps(
            {
                "shots": [
                    {
                        "shot_id": "s1",
                        "scene_index": 0,
                        "visual_description": "v",
                        "narration": "n",
                        "duration_s": 3.0,
                        "importance": 5,
                        "motion": "pan_left",
                    }
                ]
            }
        )
        board = await storyboard_planner(
            script=self._script(),
            llm=lambda **kw: {"content": resp},
        )
        assert board.shots[0].motion == "pan_left"

    async def test_motion_null_compat(self) -> None:
        from oskill.storyboard_planner import storyboard_planner

        resp = json.dumps(
            {
                "shots": [
                    {
                        "shot_id": "s1",
                        "scene_index": 0,
                        "visual_description": "v",
                        "narration": "n",
                        "duration_s": 3.0,
                        "importance": 5,
                        "motion": None,
                    }
                ]
            }
        )
        board = await storyboard_planner(
            script=self._script(),
            llm=lambda **kw: {"content": resp},
        )
        assert board.shots[0].motion is None

    async def test_motion_absent_defaults_none(self) -> None:
        from oskill.storyboard_planner import storyboard_planner

        resp = json.dumps(
            {
                "shots": [
                    {
                        "shot_id": "s1",
                        "scene_index": 0,
                        "visual_description": "v",
                        "narration": "n",
                        "duration_s": 3.0,
                        "importance": 5,
                    }
                ]
            }
        )
        board = await storyboard_planner(
            script=self._script(),
            llm=lambda **kw: {"content": resp},
        )
        assert board.shots[0].motion is None

    async def test_prompt_mentions_motion(self) -> None:
        from oskill.storyboard_planner import storyboard_planner

        calls: list[dict[str, Any]] = []

        def _llm(**kw: Any) -> dict[str, Any]:
            calls.append(kw)
            return {
                "content": json.dumps(
                    {
                        "shots": [
                            {
                                "shot_id": "s1",
                                "scene_index": 0,
                                "visual_description": "v",
                                "narration": "n",
                                "duration_s": 3.0,
                                "importance": 5,
                            }
                        ]
                    }
                )
            }

        await storyboard_planner(script=self._script(), llm=_llm)
        system = calls[0]["messages"][0]["content"]
        assert "motion" in system


# ═══════════════════════════════════════════════════════════════════════════════
# P7-B4: script_writer subjects parameter
# ═══════════════════════════════════════════════════════════════════════════════


class TestScriptWriterSubjects:
    _RESP = json.dumps(
        {
            "title": "T",
            "description": "d",
            "scenes": [
                {"index": 0, "narration": "n", "duration_s": 5.0, "visual_description": "v"}
            ],
            "estimated_duration_s": 5.0,
        }
    )

    def _make_capturing_llm(self, calls: list[dict[str, Any]]) -> Any:
        def _llm(**kw: Any) -> dict[str, Any]:
            calls.append(kw)
            return {"content": self._RESP}

        return _llm

    async def test_subjects_none_prompt_unchanged(self) -> None:
        """subjects=None → system prompt identical to Phase-6 behaviour."""
        from oskill.script_writer import script_writer

        calls: list[dict[str, Any]] = []
        await script_writer(
            topic="cats",
            target_duration_s=60,
            llm=self._make_capturing_llm(calls),
            subjects=None,
        )
        system = calls[0]["messages"][0]["content"]
        assert "以下角色" not in system

    async def test_subjects_single_injected(self) -> None:
        """subjects=[1 ref] → character name+description appear in system prompt."""
        from oskill._schemas import SubjectRef
        from oskill.script_writer import script_writer

        calls: list[dict[str, Any]] = []
        refs = [SubjectRef(subject_id="h1", name="Alice", description="主角侦探")]
        await script_writer(
            topic="mystery",
            target_duration_s=60,
            llm=self._make_capturing_llm(calls),
            subjects=refs,
        )
        system = calls[0]["messages"][0]["content"]
        assert "以下角色将出现在视频中" in system
        assert "Alice" in system
        assert "主角侦探" in system

    async def test_subjects_multi_all_injected(self) -> None:
        """subjects=[3 refs] → all three names appear in system prompt."""
        from oskill._schemas import SubjectRef
        from oskill.script_writer import script_writer

        calls: list[dict[str, Any]] = []
        refs = [
            SubjectRef(subject_id="a", name="Alice", description="侦探"),
            SubjectRef(subject_id="b", name="Bob", description="嫌疑人"),
            SubjectRef(subject_id="c", name="Carol", description="受害者"),
        ]
        await script_writer(
            topic="crime",
            target_duration_s=120,
            llm=self._make_capturing_llm(calls),
            subjects=refs,
        )
        system = calls[0]["messages"][0]["content"]
        for name in ("Alice", "Bob", "Carol"):
            assert name in system


# ═══════════════════════════════════════════════════════════════════════════════
# P7-B4: storyboard_planner subjects + style_marker + lighting_control
# ═══════════════════════════════════════════════════════════════════════════════


class TestStoryboardPlannerP7B4:
    _SHOT_RESP = json.dumps(
        {
            "shots": [
                {
                    "shot_id": "s1",
                    "scene_index": 0,
                    "visual_description": "v",
                    "narration": "n",
                    "duration_s": 3.0,
                    "importance": 5,
                }
            ]
        }
    )

    def _script(self) -> Script:
        return Script(
            title="T",
            description="d",
            scenes=[{"index": 0, "narration": "n", "duration_s": 5.0, "visual_description": "v"}],
            estimated_duration_s=5.0,
        )

    def _make_capturing_llm(self, calls: list[dict[str, Any]]) -> Any:
        def _llm(**kw: Any) -> dict[str, Any]:
            calls.append(kw)
            return {"content": self._SHOT_RESP}

        return _llm

    async def test_all_none_backward_compat(self) -> None:
        """subjects=None, style_marker=None, lighting_control=None → same as Phase 6."""
        from oskill.storyboard_planner import storyboard_planner

        calls: list[dict[str, Any]] = []
        board = await storyboard_planner(
            script=self._script(),
            llm=self._make_capturing_llm(calls),
            subjects=None,
            style_marker=None,
            lighting_control=None,
        )
        assert len(board.shots) == 1
        system = calls[0]["messages"][0]["content"]
        assert "以下角色" not in system
        assert "风格" not in system
        assert "lighting:" not in system

    async def test_subjects_injected(self) -> None:
        """subjects=[...] → character names appear in system prompt."""
        from oskill._schemas import SubjectRef
        from oskill.storyboard_planner import storyboard_planner

        calls: list[dict[str, Any]] = []
        refs = [SubjectRef(subject_id="x", name="Zara", description="女主角")]
        await storyboard_planner(
            script=self._script(),
            llm=self._make_capturing_llm(calls),
            subjects=refs,
        )
        system = calls[0]["messages"][0]["content"]
        assert "以下角色将出现在分镜中" in system
        assert "Zara" in system
        assert "女主角" in system

    async def test_style_marker_injected(self) -> None:
        """style_marker='科普' → style suffix appears in system prompt via oprim."""
        from oskill.storyboard_planner import storyboard_planner

        calls: list[dict[str, Any]] = []
        await storyboard_planner(
            script=self._script(),
            llm=self._make_capturing_llm(calls),
            style_marker="科普",
        )
        system = calls[0]["messages"][0]["content"]
        assert "科普" in system

    async def test_lighting_control_injected(self) -> None:
        """lighting_control='暖' → lighting suffix appears in system prompt via oprim."""
        from oskill.storyboard_planner import storyboard_planner

        calls: list[dict[str, Any]] = []
        await storyboard_planner(
            script=self._script(),
            llm=self._make_capturing_llm(calls),
            lighting_control="暖",
        )
        system = calls[0]["messages"][0]["content"]
        assert "lighting:" in system

    async def test_all_params_combined(self) -> None:
        """subjects + style_marker + lighting_control all injected simultaneously."""
        from oskill._schemas import SubjectRef
        from oskill.storyboard_planner import storyboard_planner

        calls: list[dict[str, Any]] = []
        refs = [SubjectRef(subject_id="p", name="Pan", description="英雄")]
        await storyboard_planner(
            script=self._script(),
            llm=self._make_capturing_llm(calls),
            subjects=refs,
            style_marker="热血",
            lighting_control="戏剧",
        )
        system = calls[0]["messages"][0]["content"]
        assert "Pan" in system
        assert "热血" in system
        assert "lighting:" in system
