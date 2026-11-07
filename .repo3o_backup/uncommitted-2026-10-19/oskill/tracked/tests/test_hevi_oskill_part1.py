"""Tests for hevi oskill: script_writer, storyboard_planner, shot_generator, consistency_check."""

from __future__ import annotations

import json
from typing import Any

import pytest

from oskill._schemas import Scene, Script, Shot, ShotPlan, Storyboard
from oskill.consistency_check import ConsistencyCheckError, consistency_check
from oskill.script_writer import ScriptWriterError, script_writer
from oskill.shot_generator import ShotGeneratorError, shot_generator
from oskill.storyboard_planner import StoryboardPlannerError, storyboard_planner

# --- Fixtures ---


def _make_llm(response: dict[str, Any] | list[Any] | str):
    """Create a mock LLM that returns given JSON."""

    def _llm(*, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        if isinstance(response, str):
            return {"content": response}
        return {"content": json.dumps(response, ensure_ascii=False)}

    return _llm


def _make_script() -> Script:
    return Script(
        title="Test",
        description="Desc",
        scenes=[Scene(index=0, narration="Hello", duration_s=5.0, visual_description="A cat")],
        estimated_duration_s=5.0,
    )


def _make_storyboard() -> Storyboard:
    return Storyboard(
        shots=[
            Shot(
                shot_id="s1",
                scene_index=0,
                visual_description="cat",
                narration="Hi",
                duration_s=3.0,
                importance=8,
            ),
            Shot(
                shot_id="s2",
                scene_index=0,
                visual_description="dog",
                narration="Bye",
                duration_s=2.0,
                importance=5,
            ),
        ]
    )


# --- script_writer tests ---


class TestScriptWriter:
    async def test_normal_generation(self) -> None:
        data = {
            "title": "T",
            "description": "D",
            "scenes": [{"index": 0, "narration": "Hi", "duration_s": 5, "visual_description": "V"}],
            "estimated_duration_s": 5,
        }
        result = await script_writer(topic="cats", target_duration_s=60, llm=_make_llm(data))
        assert result.title == "T"
        assert len(result.scenes) == 1

    async def test_empty_topic_raises(self) -> None:
        with pytest.raises(ScriptWriterError, match="topic must not be empty"):
            await script_writer(topic="", target_duration_s=60, llm=_make_llm({}))

    async def test_invalid_json_raises(self) -> None:
        with pytest.raises(ScriptWriterError, match="invalid JSON"):
            await script_writer(topic="x", target_duration_s=60, llm=_make_llm("not json"))

    async def test_validation_failure_raises(self) -> None:
        with pytest.raises(ScriptWriterError, match="validation failed"):
            await script_writer(topic="x", target_duration_s=60, llm=_make_llm({"bad": True}))

    async def test_template_prompt_used(self) -> None:
        captured: list[dict[str, Any]] = []

        def _llm(*, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
            captured.append(messages[0])
            return {
                "content": json.dumps(
                    {
                        "title": "T",
                        "description": "D",
                        "scenes": [
                            {
                                "index": 0,
                                "narration": "N",
                                "duration_s": 5,
                                "visual_description": "V",
                            }
                        ],
                        "estimated_duration_s": 5,
                    }
                )
            }

        await script_writer(topic="x", target_duration_s=60, llm=_llm, template_prompt="CUSTOM")
        assert captured[0]["content"] == "CUSTOM"

    async def test_multiple_scenes(self) -> None:
        data = {
            "title": "T",
            "description": "D",
            "scenes": [
                {"index": i, "narration": f"N{i}", "duration_s": 5, "visual_description": f"V{i}"}
                for i in range(5)
            ],
            "estimated_duration_s": 25,
        }
        result = await script_writer(topic="x", target_duration_s=25, llm=_make_llm(data))
        assert len(result.scenes) == 5

    async def test_language_param(self) -> None:
        captured: list[dict[str, Any]] = []

        def _llm(*, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
            captured.append(messages[0])
            return {
                "content": json.dumps(
                    {
                        "title": "T",
                        "description": "D",
                        "scenes": [
                            {
                                "index": 0,
                                "narration": "N",
                                "duration_s": 5,
                                "visual_description": "V",
                            }
                        ],
                        "estimated_duration_s": 5,
                    }
                )
            }

        await script_writer(topic="x", target_duration_s=60, llm=_llm, language="en")
        assert "en" in captured[0]["content"]

    async def test_estimated_duration(self) -> None:
        data = {
            "title": "T",
            "description": "D",
            "scenes": [{"index": 0, "narration": "N", "duration_s": 30, "visual_description": "V"}],
            "estimated_duration_s": 30,
        }
        result = await script_writer(topic="x", target_duration_s=30, llm=_make_llm(data))
        assert result.estimated_duration_s == 30


# --- storyboard_planner tests ---


class TestStoryboardPlanner:
    async def test_normal_planning(self) -> None:
        data = {
            "shots": [
                {
                    "shot_id": "s1",
                    "scene_index": 0,
                    "visual_description": "V",
                    "narration": "N",
                    "duration_s": 2,
                    "importance": 5,
                }
            ]
        }
        result = await storyboard_planner(script=_make_script(), llm=_make_llm(data))
        assert len(result.shots) == 1

    async def test_empty_script_raises(self) -> None:
        empty = Script(title="T", description="D", scenes=[], estimated_duration_s=0)
        with pytest.raises(StoryboardPlannerError, match="no scenes"):
            await storyboard_planner(script=empty, llm=_make_llm({}))

    async def test_invalid_json_raises(self) -> None:
        with pytest.raises(StoryboardPlannerError, match="invalid JSON"):
            await storyboard_planner(script=_make_script(), llm=_make_llm("bad"))

    async def test_validation_failure(self) -> None:
        with pytest.raises(StoryboardPlannerError, match="validation failed"):
            await storyboard_planner(script=_make_script(), llm=_make_llm({"shots": "bad"}))

    async def test_multiple_shots(self) -> None:
        data = {
            "shots": [
                {
                    "shot_id": f"s{i}",
                    "scene_index": 0,
                    "visual_description": "V",
                    "narration": "N",
                    "duration_s": 1,
                    "importance": i,
                }
                for i in range(5)
            ]
        }
        result = await storyboard_planner(script=_make_script(), llm=_make_llm(data))
        assert len(result.shots) == 5

    async def test_importance_field(self) -> None:
        data = {
            "shots": [
                {
                    "shot_id": "s1",
                    "scene_index": 0,
                    "visual_description": "V",
                    "narration": "N",
                    "duration_s": 2,
                    "importance": 9,
                }
            ]
        }
        result = await storyboard_planner(script=_make_script(), llm=_make_llm(data))
        assert result.shots[0].importance == 9

    async def test_motion_field(self) -> None:
        data = {
            "shots": [
                {
                    "shot_id": "s1",
                    "scene_index": 0,
                    "visual_description": "V",
                    "narration": "N",
                    "duration_s": 2,
                    "importance": 5,
                    "motion": "pan_left",
                }
            ]
        }
        result = await storyboard_planner(script=_make_script(), llm=_make_llm(data))
        assert result.shots[0].motion == "pan_left"

    async def test_shots_per_scene_params(self) -> None:
        data = {
            "shots": [
                {
                    "shot_id": "s1",
                    "scene_index": 0,
                    "visual_description": "V",
                    "narration": "N",
                    "duration_s": 2,
                    "importance": 5,
                }
            ]
        }
        result = await storyboard_planner(
            script=_make_script(),
            llm=_make_llm(data),
            shots_per_scene_min=1,
            shots_per_scene_max=5,
        )
        assert len(result.shots) >= 1


# --- shot_generator tests ---


class TestShotGenerator:
    async def test_normal_generation(self) -> None:
        data = [
            {"shot_id": "s1", "image_prompt": "cat photo", "tts_text": "Hi", "duration_s": 3},
            {"shot_id": "s2", "image_prompt": "dog photo", "tts_text": "Bye", "duration_s": 2},
        ]
        result = await shot_generator(storyboard=_make_storyboard(), llm=_make_llm(data))
        assert len(result) == 2
        assert result[0].image_prompt == "cat photo"

    async def test_empty_storyboard_raises(self) -> None:
        empty = Storyboard(shots=[])
        with pytest.raises(ShotGeneratorError, match="no shots"):
            await shot_generator(storyboard=empty, llm=_make_llm([]))

    async def test_invalid_json_raises(self) -> None:
        with pytest.raises(ShotGeneratorError, match="invalid JSON"):
            await shot_generator(storyboard=_make_storyboard(), llm=_make_llm("bad"))

    async def test_count_mismatch_raises(self) -> None:
        data = [{"shot_id": "s1", "image_prompt": "x", "tts_text": "y", "duration_s": 1}]
        with pytest.raises(ShotGeneratorError, match="count mismatch"):
            await shot_generator(storyboard=_make_storyboard(), llm=_make_llm(data))

    async def test_validation_failure(self) -> None:
        data = [{"bad": True}, {"bad": True}]
        with pytest.raises(ShotGeneratorError, match="validation failed"):
            await shot_generator(storyboard=_make_storyboard(), llm=_make_llm(data))

    async def test_not_array_raises(self) -> None:
        with pytest.raises(ShotGeneratorError, match="Expected JSON array"):
            await shot_generator(storyboard=_make_storyboard(), llm=_make_llm({"not": "array"}))

    async def test_prompt_non_empty(self) -> None:
        data = [
            {"shot_id": "s1", "image_prompt": "prompt1", "tts_text": "text1", "duration_s": 3},
            {"shot_id": "s2", "image_prompt": "prompt2", "tts_text": "text2", "duration_s": 2},
        ]
        result = await shot_generator(storyboard=_make_storyboard(), llm=_make_llm(data))
        assert all(p.image_prompt for p in result)

    async def test_duration_preserved(self) -> None:
        data = [
            {"shot_id": "s1", "image_prompt": "p", "tts_text": "t", "duration_s": 3.5},
            {"shot_id": "s2", "image_prompt": "p", "tts_text": "t", "duration_s": 2.5},
        ]
        result = await shot_generator(storyboard=_make_storyboard(), llm=_make_llm(data))
        assert result[0].duration_s == 3.5


# --- consistency_check tests ---


class TestConsistencyCheck:
    async def test_normal_pass(self) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="t", duration_s=3)]
        data = {"issues": [], "overall_score": 0.95}
        result = await consistency_check(shots=shots, llm=_make_llm(data))
        assert result.overall_score == 0.95
        assert result.issues == []

    async def test_with_issues(self) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="t", duration_s=3)]
        data = {
            "issues": [{"shot_id": "s1", "description": "color mismatch", "severity": "high"}],
            "overall_score": 0.6,
        }
        result = await consistency_check(shots=shots, llm=_make_llm(data))
        assert len(result.issues) == 1

    async def test_empty_shots_raises(self) -> None:
        with pytest.raises(ConsistencyCheckError, match="must not be empty"):
            await consistency_check(shots=[], llm=_make_llm({}))

    async def test_invalid_json_raises(self) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="t", duration_s=3)]
        with pytest.raises(ConsistencyCheckError, match="invalid JSON"):
            await consistency_check(shots=shots, llm=_make_llm("bad"))

    async def test_validation_failure(self) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="t", duration_s=3)]
        with pytest.raises(ConsistencyCheckError, match="validation failed"):
            await consistency_check(shots=shots, llm=_make_llm({"bad": True}))

    async def test_score_boundary_zero(self) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="t", duration_s=3)]
        data = {"issues": [], "overall_score": 0.0}
        result = await consistency_check(shots=shots, llm=_make_llm(data))
        assert result.overall_score == 0.0

    async def test_score_boundary_one(self) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="t", duration_s=3)]
        data = {"issues": [], "overall_score": 1.0}
        result = await consistency_check(shots=shots, llm=_make_llm(data))
        assert result.overall_score == 1.0

    async def test_multiple_issues(self) -> None:
        shots = [ShotPlan(shot_id="s1", image_prompt="p", tts_text="t", duration_s=3)]
        data = {
            "issues": [
                {"shot_id": "s1", "description": "issue1", "severity": "low"},
                {"shot_id": "s1", "description": "issue2", "severity": "high"},
            ],
            "overall_score": 0.4,
        }
        result = await consistency_check(shots=shots, llm=_make_llm(data))
        assert len(result.issues) == 2
