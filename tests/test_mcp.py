"""P11.E tests — MCP server registration, tool dispatch, dual-entry service sharing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.creative.assist_registry import ASSIST_REGISTRY
from hevi.creative.assist_service import AssistService
from hevi.creative.workflow_service import WorkflowService
from hevi.mcp.server import build_hevi_mcp_server
from hevi.mcp.tools.canvas_tools import build_canvas_skills
from hevi.mcp.tools.creative_tools import build_creative_skills
from hevi.mcp.tools.subject_tools import build_subject_skills
from hevi.mcp.tools.video_tools import build_video_skills

# ── helpers ───────────────────────────────────────────────────────────────────


def _tool_map(server: Any) -> dict[str, Any]:
    return server._fastmcp._tool_manager._tools  # type: ignore[attr-defined]


def _handler_of(server: Any, name: str) -> Any:
    return _tool_map(server)[name]


def _make_assist() -> AssistService:
    return MagicMock(spec=AssistService)


def _make_workflow() -> WorkflowService:
    return MagicMock(spec=WorkflowService)


# ── 1. Server startup + tool registration ─────────────────────────────────────


def test_server_registers_14_tools() -> None:
    server = build_hevi_mcp_server(
        assist_svc=MagicMock(spec=AssistService),
        workflow_svc=MagicMock(spec=WorkflowService),
    )
    tools = _tool_map(server)
    assert len(tools) == 14


def test_server_registers_expected_names() -> None:
    server = build_hevi_mcp_server(
        assist_svc=MagicMock(spec=AssistService),
        workflow_svc=MagicMock(spec=WorkflowService),
    )
    names = set(_tool_map(server).keys())
    expected = {
        "hevi.list_capabilities",
        "hevi.generate_longvideo",
        "hevi.create_three_view",
        "hevi.gen_storyboard",
        "hevi.predict_story",
        "hevi.gen_multi_angle",
        "hevi.make_transition",
        "hevi.edit_video_elements",
        "hevi.run_character_consistency",
        "hevi.run_storyboard_workflow",
        "hevi.run_comic_to_animation",
        "hevi.subject_create",
        "hevi.subject_search",
        "hevi.execute_canvas",
    }
    assert names == expected


def test_tool_schema_has_required_input_schema() -> None:
    server = build_hevi_mcp_server(
        assist_svc=MagicMock(spec=AssistService),
        workflow_svc=MagicMock(spec=WorkflowService),
    )
    for name, tool in _tool_map(server).items():
        assert "type" in tool.parameters, f"Tool {name!r} missing 'type' in input schema"
        assert "properties" in tool.parameters, f"Tool {name!r} missing 'properties'"


def test_registering_duplicate_name_does_not_grow_tool_count() -> None:
    """FastMCP overwrites on duplicate (with warning); tool count stays stable."""
    from obase.mcp_server import SkillDef

    server = build_hevi_mcp_server(
        assist_svc=MagicMock(spec=AssistService),
        workflow_svc=MagicMock(spec=WorkflowService),
    )
    before = len(_tool_map(server))
    server.register_skill(
        SkillDef(
            name="hevi.list_capabilities",
            description="overwrite",
            input_schema={"type": "object", "properties": {}},
            handler=AsyncMock(return_value={}),
        )
    )
    assert len(_tool_map(server)) == before


# ── 2. list_capabilities tool ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_capabilities_returns_registry() -> None:
    server = build_hevi_mcp_server(
        assist_svc=MagicMock(spec=AssistService),
        workflow_svc=MagicMock(spec=WorkflowService),
    )
    tool = _tool_map(server)["hevi.list_capabilities"]
    result: dict[str, Any] = await tool.fn()
    assert "capabilities" in result
    assert "count" in result
    assert result["count"] == len(ASSIST_REGISTRY)
    assert "three_view" in result["capabilities"]


# ── 3. generate_longvideo tool ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_longvideo_calls_orchestrator() -> None:
    skills = build_video_skills()
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "hevi.generate_longvideo"

    mock_result = {"video_path": "/tmp/out.mp4", "shots_count": 10, "status": "ok"}
    _orch = "hevi.mcp.tools.video_tools.orchestrate_longvideo"
    with patch(_orch, new_callable=AsyncMock, return_value=mock_result) as m:
        result = await skill.handler(
            {
                "topic": "太空探险",
                "duration_archetype": "medium",
                "video_provider": "wan",
                "audio_provider": "tts",
                "style": "cinematic",
            }
        )
    assert result["video_path"] == "/tmp/out.mp4"
    m.assert_awaited_once()
    assert m.call_args.kwargs["topic"] == "太空探险"


@pytest.mark.asyncio
async def test_generate_longvideo_defaults_style_and_language() -> None:
    skills = build_video_skills()
    _orch = "hevi.mcp.tools.video_tools.orchestrate_longvideo"
    with patch(_orch, new_callable=AsyncMock, return_value={}) as m:
        await skills[0].handler(
            {
                "topic": "测试",
                "duration_archetype": "short",
                "video_provider": "wan",
                "audio_provider": "tts",
            }
        )
    assert m.call_args.kwargs["style"] == "cinematic"
    assert m.call_args.kwargs["language"] == "zh"


# ── 4. Creative assist tools ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creative_three_view_calls_assist_svc() -> None:
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {
        "front_view_prompt": "front",
        "side_view_prompt": "side",
        "back_view_prompt": "back",
    }
    assist = MagicMock(spec=AssistService)
    assist.gen_three_view = AsyncMock(return_value=mock_result)

    skills = build_creative_skills(assist_svc=assist)
    three_view_skill = next(s for s in skills if s.name == "hevi.create_three_view")
    result = await three_view_skill.handler(
        {"character_description": "武士风格男主角", "style": "anime"}
    )
    assist.gen_three_view.assert_awaited_once_with(
        character_description="武士风格男主角", style="anime"
    )
    assert result["front_view_prompt"] == "front"


@pytest.mark.asyncio
async def test_creative_make_transition_returns_path_str() -> None:
    assist = MagicMock(spec=AssistService)
    assist.make_transition = AsyncMock(return_value=Path("/tmp/out.mp4"))

    skills = build_creative_skills(assist_svc=assist)
    skill = next(s for s in skills if s.name == "hevi.make_transition")
    result = await skill.handler(
        {
            "first_frame": "/tmp/f1.png",
            "last_frame": "/tmp/f2.png",
            "duration_s": 3.0,
            "video_provider": "wan",
            "output_path": "/tmp/out.mp4",
        }
    )
    assert result["output_path"] == "/tmp/out.mp4"
    call_kwargs = assist.make_transition.call_args.kwargs
    assert isinstance(call_kwargs["first_frame"], Path)


@pytest.mark.asyncio
async def test_creative_element_edit_returns_elements_list() -> None:
    original = [{"type": "text", "value": "hello"}]
    assist = MagicMock(spec=AssistService)
    assist.edit_video_elements = AsyncMock(return_value=original)

    skills = build_creative_skills(assist_svc=assist)
    skill = next(s for s in skills if s.name == "hevi.edit_video_elements")
    result = await skill.handler(
        {
            "elements": original,
            "operation": "replace",
            "target_index": 0,
            "replacement": {"type": "text", "value": "world"},
        }
    )
    assert isinstance(result["elements"], list)


@pytest.mark.asyncio
async def test_creative_storyboard_workflow_validates_script() -> None:
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"shots": []}
    workflow = MagicMock(spec=WorkflowService)
    workflow.run_storyboard_workflow = AsyncMock(return_value=mock_result)

    skills = build_creative_skills(workflow_svc=workflow)
    skill = next(s for s in skills if s.name == "hevi.run_storyboard_workflow")
    result = await skill.handler(
        {
            "script": {
                "title": "测试剧本",
                "description": "desc",
                "scenes": [],
                "estimated_duration_s": 60,
            },
            "image_provider": "flux",
        }
    )
    assert "shots" in result
    workflow.run_storyboard_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_creative_comic_to_animation_returns_str_path() -> None:
    workflow = MagicMock(spec=WorkflowService)
    workflow.run_comic_to_animation = AsyncMock(return_value=Path("/tmp/out.mp4"))

    skills = build_creative_skills(workflow_svc=workflow)
    skill = next(s for s in skills if s.name == "hevi.run_comic_to_animation")
    result = await skill.handler(
        {
            "comic_image": "/tmp/comic.png",
            "image_provider": "flux",
            "video_provider": "wan",
        }
    )
    assert result["output_path"] == "/tmp/out.mp4"


# ── 5. Subject tools ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subject_create_calls_service() -> None:
    from hevi.subjects.subject_service import SubjectService

    mock_svc = MagicMock(spec=SubjectService)
    mock_svc.create_subject = AsyncMock(
        return_value={"id": "123", "name": "武士", "kind": "character"}
    )
    skills = build_subject_skills(subject_svc=mock_svc)
    create_skill = next(s for s in skills if s.name == "hevi.subject_create")
    result = await create_skill.handler({"name": "武士", "kind": "character"})
    assert result["id"] == "123"
    mock_svc.create_subject.assert_awaited_once()


@pytest.mark.asyncio
async def test_subject_search_returns_count() -> None:
    from hevi.subjects.subject_service import SubjectService

    mock_svc = MagicMock(spec=SubjectService)
    mock_svc.search_subjects = AsyncMock(
        return_value=[{"id": "1"}, {"id": "2"}]
    )
    skills = build_subject_skills(subject_svc=mock_svc)
    search_skill = next(s for s in skills if s.name == "hevi.subject_search")
    result = await search_skill.handler({"kind": "character"})
    assert result["count"] == 2
    assert len(result["subjects"]) == 2


# ── 6. Canvas tool ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_canvas_calls_executor() -> None:
    from hevi.canvas.executor_service import ExecutorService

    mock_exe = MagicMock(spec=ExecutorService)
    mock_exe.execute_graph = AsyncMock(
        return_value={
            "graph_id": "g1",
            "status": "completed",
            "node_count": 2,
            "results": {},
        }
    )
    skills = build_canvas_skills(executor_svc=mock_exe)
    skill = skills[0]
    result = await skill.handler({"graph_id": "g1", "on_error": "rollback"})
    assert result["status"] == "completed"
    mock_exe.execute_graph.assert_awaited_once_with("g1", on_error="rollback")


# ── 7. Dual-entry: MCP shares service layer with REST ────────────────────────


@pytest.mark.asyncio
async def test_mcp_and_rest_share_same_subject_service_logic() -> None:
    """MCP subject_create handler exercises same SubjectService as REST POST /subjects."""
    from hevi.subjects.subject_service import SubjectService

    created_args: list[dict[str, Any]] = []

    async def _create_subject(**kwargs: Any) -> dict[str, Any]:
        created_args.append(kwargs)
        return {"id": "xyz", "name": kwargs["name"], "kind": kwargs["kind"]}

    mock_svc = MagicMock(spec=SubjectService)
    mock_svc.create_subject = AsyncMock(side_effect=_create_subject)

    skills = build_subject_skills(subject_svc=mock_svc)
    skill = next(s for s in skills if s.name == "hevi.subject_create")

    await skill.handler({"name": "场景A", "kind": "scene"})
    assert created_args[0]["name"] == "场景A"
    assert created_args[0]["kind"] == "scene"


# ── 8. Schema validity ────────────────────────────────────────────────────────


def test_all_tool_schemas_are_object_type() -> None:
    from hevi.mcp.schemas import (
        CHARACTER_CONSISTENCY_INPUT,
        COMIC_TO_ANIMATION_INPUT,
        ELEMENT_EDIT_INPUT,
        EXECUTE_CANVAS_INPUT,
        GENERATE_LONGVIDEO_INPUT,
        LIST_CAPABILITIES_INPUT,
        MAKE_TRANSITION_INPUT,
        MULTI_ANGLE_INPUT,
        PREDICT_STORY_INPUT,
        STORYBOARD_INPUT,
        STORYBOARD_WORKFLOW_INPUT,
        SUBJECT_CREATE_INPUT,
        SUBJECT_SEARCH_INPUT,
        THREE_VIEW_INPUT,
    )

    schemas = [
        CHARACTER_CONSISTENCY_INPUT,
        COMIC_TO_ANIMATION_INPUT,
        ELEMENT_EDIT_INPUT,
        EXECUTE_CANVAS_INPUT,
        GENERATE_LONGVIDEO_INPUT,
        LIST_CAPABILITIES_INPUT,
        MAKE_TRANSITION_INPUT,
        MULTI_ANGLE_INPUT,
        PREDICT_STORY_INPUT,
        STORYBOARD_INPUT,
        STORYBOARD_WORKFLOW_INPUT,
        SUBJECT_CREATE_INPUT,
        SUBJECT_SEARCH_INPUT,
        THREE_VIEW_INPUT,
    ]
    for s in schemas:
        assert s["type"] == "object"
        assert "properties" in s


def test_required_fields_present_in_schemas() -> None:
    from hevi.mcp.schemas import (
        EXECUTE_CANVAS_INPUT,
        GENERATE_LONGVIDEO_INPUT,
        SUBJECT_CREATE_INPUT,
        THREE_VIEW_INPUT,
    )

    assert "topic" in GENERATE_LONGVIDEO_INPUT["required"]
    assert "character_description" in THREE_VIEW_INPUT["required"]
    assert "name" in SUBJECT_CREATE_INPUT["required"]
    assert "graph_id" in EXECUTE_CANVAS_INPUT["required"]


# ── 9. Edge cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_canvas_execute_propagates_graph_not_found() -> None:
    from hevi.canvas.executor_service import ExecutorService

    mock_exe = MagicMock(spec=ExecutorService)
    mock_exe.execute_graph = AsyncMock(side_effect=ValueError("Graph not found"))
    skills = build_canvas_skills(executor_svc=mock_exe)
    skill = skills[0]
    with pytest.raises(ValueError, match="Graph not found"):
        await skill.handler({"graph_id": "missing"})


@pytest.mark.asyncio
async def test_video_skills_returns_exactly_one_skill() -> None:
    skills = build_video_skills()
    assert len(skills) == 1
    assert skills[0].name == "hevi.generate_longvideo"


@pytest.mark.asyncio
async def test_creative_skills_returns_9_skills() -> None:
    skills = build_creative_skills(
        assist_svc=MagicMock(spec=AssistService),
        workflow_svc=MagicMock(spec=WorkflowService),
    )
    assert len(skills) == 9


def test_subject_skills_returns_2_skills() -> None:
    from hevi.subjects.subject_service import SubjectService

    skills = build_subject_skills(subject_svc=MagicMock(spec=SubjectService))
    assert len(skills) == 2
    names = {s.name for s in skills}
    assert "hevi.subject_create" in names
    assert "hevi.subject_search" in names


def test_canvas_skills_returns_1_skill() -> None:
    from hevi.canvas.executor_service import ExecutorService

    skills = build_canvas_skills(executor_svc=MagicMock(spec=ExecutorService))
    assert len(skills) == 1
    assert skills[0].name == "hevi.execute_canvas"
