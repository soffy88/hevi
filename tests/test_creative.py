"""P11.B tests — creative assist service, workflow service, reference_link, API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.creative.assist_registry import ASSIST_REGISTRY
from hevi.creative.assist_service import AssistService
from hevi.creative.reference_link import resolve_reference
from hevi.creative.workflow_service import WorkflowService

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def assist() -> AssistService:
    return AssistService(caller=MagicMock(), llm=MagicMock())


@pytest.fixture
def workflow() -> WorkflowService:
    return WorkflowService(llm=MagicMock())


# ── 1. AssistService — gen_three_view ────────────────────────────────────────


@pytest.mark.asyncio
async def test_gen_three_view_valid(assist: AssistService) -> None:
    from oprim.character_three_view import ThreeViewResult

    expected = ThreeViewResult(
        front_prompt="front", side_prompt="side", back_prompt="back"
    )
    with patch(
        "hevi.creative.assist_service.character_three_view",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_fn:
        result = await assist.gen_three_view(character_description="A hero warrior")
    assert result.front_prompt == "front"
    mock_fn.assert_awaited_once()
    assert mock_fn.call_args.args[0] == "A hero warrior"


@pytest.mark.asyncio
async def test_gen_three_view_empty_description_raises(assist: AssistService) -> None:
    with pytest.raises(ValueError, match="character_description must not be empty"):
        await assist.gen_three_view(character_description="   ")


# ── 2. AssistService — gen_storyboard ────────────────────────────────────────


@pytest.mark.asyncio
async def test_gen_storyboard_valid(assist: AssistService) -> None:
    from oprim.storyboard_grid import StoryboardGridResult

    expected = StoryboardGridResult(shots=[], grid_description="6-shot", total_duration_s=30.0)
    with patch(
        "hevi.creative.assist_service.storyboard_grid",
        new_callable=AsyncMock,
        return_value=expected,
    ):
        result = await assist.gen_storyboard(script_text="Hero fights dragon")
    assert result.total_duration_s == 30.0


@pytest.mark.asyncio
async def test_gen_storyboard_empty_script_raises(assist: AssistService) -> None:
    with pytest.raises(ValueError, match="script_text must not be empty"):
        await assist.gen_storyboard(script_text="")


@pytest.mark.asyncio
async def test_gen_storyboard_zero_shots_raises(assist: AssistService) -> None:
    with pytest.raises(ValueError, match="shots must be >= 1"):
        await assist.gen_storyboard(script_text="text", shots=0)


# ── 3. AssistService — predict_story ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_predict_story_forward(assist: AssistService) -> None:
    from oprim.story_predict import StoryPrediction, TimePrediction

    expected = StoryPrediction(
        forward=[TimePrediction(seconds=3, description="hero runs")], backward=[]
    )
    with patch(
        "hevi.creative.assist_service.story_predict",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_fn:
        result = await assist.predict_story(
            reference_image=Path("/tmp/frame.png"), direction="forward"
        )
    assert result.forward[0].seconds == 3
    assert result.backward == []
    assert mock_fn.call_args.kwargs["direction"] == "forward"


@pytest.mark.asyncio
async def test_predict_story_backward(assist: AssistService) -> None:
    from oprim.story_predict import StoryPrediction, TimePrediction

    expected = StoryPrediction(
        forward=[],
        backward=[TimePrediction(seconds=-5, description="setup scene")],
    )
    with patch(
        "hevi.creative.assist_service.story_predict",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_fn:
        result = await assist.predict_story(
            reference_image=Path("/tmp/frame.png"), direction="backward"
        )
    assert result.backward[0].seconds == -5
    assert mock_fn.call_args.kwargs["direction"] == "backward"


# ── 4. AssistService — gen_multi_angle ───────────────────────────────────────


@pytest.mark.asyncio
async def test_gen_multi_angle_valid(assist: AssistService) -> None:
    from oprim.multi_angle import MultiAngleResult

    expected = MultiAngleResult(
        angle_prompts={"front": "front shot", "side": "side shot"},
        subject_description="a red car",
    )
    with patch(
        "hevi.creative.assist_service.multi_angle",
        new_callable=AsyncMock,
        return_value=expected,
    ):
        result = await assist.gen_multi_angle(subject_description="a red car")
    assert "front" in result.angle_prompts


@pytest.mark.asyncio
async def test_gen_multi_angle_empty_description_raises(assist: AssistService) -> None:
    with pytest.raises(ValueError, match="subject_description must not be empty"):
        await assist.gen_multi_angle(subject_description="  ")


# ── 5. AssistService — make_transition ───────────────────────────────────────


@pytest.mark.asyncio
async def test_make_transition_valid(assist: AssistService) -> None:
    out = Path("/tmp/transition.mp4")
    with patch(
        "hevi.creative.assist_service.first_last_frame_transition",
        new_callable=AsyncMock,
        return_value=out,
    ) as mock_fn:
        result = await assist.make_transition(
            first_frame=Path("/tmp/start.png"),
            last_frame=Path("/tmp/end.png"),
            duration_s=3.0,
            video_provider="wan22_local",
            output_path=out,
        )
    assert result == out
    assert mock_fn.call_args.kwargs["duration_s"] == 3.0
    assert mock_fn.call_args.kwargs["video_provider"] == "wan22_local"


@pytest.mark.asyncio
async def test_make_transition_negative_duration_raises(assist: AssistService) -> None:
    with pytest.raises(ValueError, match="duration_s must be positive"):
        await assist.make_transition(
            first_frame=Path("/tmp/a.png"),
            last_frame=Path("/tmp/b.png"),
            duration_s=-1.0,
            video_provider="wan22_local",
            output_path=Path("/tmp/out.mp4"),
        )


# ── 6. AssistService — edit_video_elements ───────────────────────────────────


@pytest.mark.asyncio
async def test_edit_elements_replace(assist: AssistService) -> None:
    elements: list[dict[str, Any]] = [{"type": "title", "text": "Old"}]
    expected: list[dict[str, Any]] = [{"type": "title", "text": "New"}]
    with patch(
        "hevi.creative.assist_service.video_element_edit",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_fn:
        result = await assist.edit_video_elements(
            elements=elements,
            operation="replace",
            target_index=0,
            replacement={"type": "title", "text": "New"},
        )
    assert result == expected
    assert mock_fn.call_args.kwargs["operation"] == "replace"


@pytest.mark.asyncio
async def test_edit_elements_delete(assist: AssistService) -> None:
    elements: list[dict[str, Any]] = [{"type": "title"}, {"type": "body"}]
    expected: list[dict[str, Any]] = [{"type": "body"}]
    with patch(
        "hevi.creative.assist_service.video_element_edit",
        new_callable=AsyncMock,
        return_value=expected,
    ):
        result = await assist.edit_video_elements(
            elements=elements,
            operation="delete",
            target_index=0,
        )
    assert result == expected


@pytest.mark.asyncio
async def test_edit_elements_replace_no_replacement_raises(assist: AssistService) -> None:
    with pytest.raises(ValueError, match="replacement is required"):
        await assist.edit_video_elements(
            elements=[{"type": "x"}],
            operation="replace",
            target_index=0,
            replacement=None,
        )


@pytest.mark.asyncio
async def test_edit_elements_invalid_operation_raises(assist: AssistService) -> None:
    with pytest.raises(ValueError, match="operation must be one of"):
        await assist.edit_video_elements(
            elements=[],
            operation="remove",
            target_index=0,
        )


# ── 7. reference_link ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reference_link_resolves() -> None:
    subject = {"reference_images": ["img/ada.jpg", "img/ada2.jpg"]}
    mock_svc = MagicMock()
    mock_svc.get_subject = AsyncMock(return_value=subject)
    result = await resolve_reference("sub-123", mock_svc)
    assert result == "img/ada.jpg"
    mock_svc.get_subject.assert_awaited_once_with("sub-123")


@pytest.mark.asyncio
async def test_reference_link_subject_not_found() -> None:
    mock_svc = MagicMock()
    mock_svc.get_subject = AsyncMock(return_value=None)
    result = await resolve_reference("missing", mock_svc)
    assert result is None


@pytest.mark.asyncio
async def test_reference_link_no_images_returns_none() -> None:
    subject = {"reference_images": []}
    mock_svc = MagicMock()
    mock_svc.get_subject = AsyncMock(return_value=subject)
    result = await resolve_reference("sub-456", mock_svc)
    assert result is None


# ── 8. WorkflowService — run_character_consistency ───────────────────────────


@pytest.mark.asyncio
async def test_run_character_consistency(workflow: WorkflowService) -> None:
    from oskill.character_consistency_workflow import CharacterConsistencyResult
    from oskill.character_three_view import ThreeViewResult as OskillThreeViewResult

    three_view = OskillThreeViewResult(
        front=Path("out/front.png"),
        side=Path("out/side.png"),
        back=Path("out/back.png"),
        consistency_score=0.95,
    )
    expected = CharacterConsistencyResult(
        three_view=three_view, scene_variants=[], consistency_score=0.9
    )
    with patch(
        "hevi.creative.workflow_service.character_consistency_workflow",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_fn:
        result = await workflow.run_character_consistency(
            portrait_image=Path("/tmp/face.png"),
            scene_descriptions=["hero in forest"],
            image_provider="flux",
            output_dir=Path("/tmp/out"),
        )
    assert result.consistency_score == 0.9
    assert mock_fn.call_args.kwargs["image_provider"] == "flux"


@pytest.mark.asyncio
async def test_run_character_consistency_empty_scenes_raises(
    workflow: WorkflowService,
) -> None:
    with pytest.raises(ValueError, match="scene_descriptions must not be empty"):
        await workflow.run_character_consistency(
            portrait_image=Path("/tmp/face.png"),
            scene_descriptions=[],
            image_provider="flux",
            output_dir=Path("/tmp/out"),
        )


# ── 9. WorkflowService — run_storyboard_workflow ─────────────────────────────


def _make_script() -> Any:
    from oskill._schemas import Scene, Script

    return Script(
        title="Test",
        description="",
        scenes=[
            Scene(index=0, narration="narr", duration_s=5.0, visual_description="hero")
        ],
        estimated_duration_s=5.0,
    )


@pytest.mark.asyncio
async def test_run_storyboard_workflow_grid_9(workflow: WorkflowService) -> None:
    from oskill.multi_shot_storyboard_workflow import MultiShotStoryboard

    expected = MultiShotStoryboard(shots=[], grid_preview=Path("grid.png"))
    with patch(
        "hevi.creative.workflow_service.multi_shot_storyboard_workflow",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_fn:
        result = await workflow.run_storyboard_workflow(
            script=_make_script(),
            subjects=[],
            image_provider="flux",
            output_dir=Path("/tmp/out"),
            grid_size=9,
        )
    assert result.grid_preview == Path("grid.png")
    assert mock_fn.call_args.kwargs["grid_size"] == 9


@pytest.mark.asyncio
async def test_run_storyboard_workflow_grid_25(workflow: WorkflowService) -> None:
    from oskill.multi_shot_storyboard_workflow import MultiShotStoryboard

    expected = MultiShotStoryboard(shots=[], grid_preview=Path("grid25.png"))
    with patch(
        "hevi.creative.workflow_service.multi_shot_storyboard_workflow",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_fn:
        result = await workflow.run_storyboard_workflow(
            script=_make_script(),
            subjects=[],
            image_provider="flux",
            output_dir=Path("/tmp/out"),
            grid_size=25,
        )
    assert mock_fn.call_args.kwargs["grid_size"] == 25
    assert result.grid_preview == Path("grid25.png")


# ── 10. WorkflowService — run_comic_to_animation ─────────────────────────────


@pytest.mark.asyncio
async def test_run_comic_to_animation(workflow: WorkflowService) -> None:
    out = Path("/tmp/anim.mp4")
    with patch(
        "hevi.creative.workflow_service.comic_to_animation_workflow",
        new_callable=AsyncMock,
        return_value=out,
    ) as mock_fn:
        result = await workflow.run_comic_to_animation(
            comic_image=Path("/tmp/panel.png"),
            image_provider="flux",
            video_provider="wan22_local",
            output_path=out,
        )
    assert result == out
    assert mock_fn.call_args.kwargs["video_provider"] == "wan22_local"


# ── 11. assist_registry ───────────────────────────────────────────────────────


def test_assist_registry_has_9_entries() -> None:
    assert len(ASSIST_REGISTRY) == 9


def test_assist_registry_all_have_required_keys() -> None:
    required = {"name", "inputs", "outputs", "providers", "kind"}
    for key, entry in ASSIST_REGISTRY.items():
        missing = required - entry.keys()
        assert not missing, f"Entry {key!r} missing keys: {missing}"


def test_assist_registry_kind_values() -> None:
    oprim_count = sum(1 for e in ASSIST_REGISTRY.values() if e["kind"] == "oprim")
    oskill_count = sum(1 for e in ASSIST_REGISTRY.values() if e["kind"] == "oskill")
    assert oprim_count == 6
    assert oskill_count == 3


# ── 12. API routes ────────────────────────────────────────────────────────────


def _mock_assist() -> AssistService:
    return AssistService(caller=MagicMock(), llm=MagicMock())


def _mock_workflow() -> WorkflowService:
    return WorkflowService(llm=MagicMock())


@pytest.mark.asyncio
async def test_api_three_view(client: Any) -> None:
    from oprim.character_three_view import ThreeViewResult

    from hevi.api.main import app
    from hevi.api.routers.creative import get_assist_service

    svc = _mock_assist()
    svc.gen_three_view = AsyncMock(  # type: ignore[method-assign]
        return_value=ThreeViewResult(front_prompt="fp", side_prompt="sp", back_prompt="bp")
    )
    app.dependency_overrides[get_assist_service] = lambda: svc
    resp = await client.post(
        "/api/creative/three-view",
        json={"character_description": "A samurai", "style": "anime"},
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["front_prompt"] == "fp"


@pytest.mark.asyncio
async def test_api_storyboard(client: Any) -> None:
    from oprim.storyboard_grid import StoryboardGridResult

    from hevi.api.main import app
    from hevi.api.routers.creative import get_assist_service

    svc = _mock_assist()
    svc.gen_storyboard = AsyncMock(  # type: ignore[method-assign]
        return_value=StoryboardGridResult(
            shots=[{"index": 0}], grid_description="6-shot", total_duration_s=30.0
        )
    )
    app.dependency_overrides[get_assist_service] = lambda: svc
    resp = await client.post(
        "/api/creative/storyboard",
        json={"script_text": "Scene 1", "shots": 6},
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total_duration_s"] == 30.0


@pytest.mark.asyncio
async def test_api_story_predict(client: Any) -> None:
    from oprim.story_predict import StoryPrediction, TimePrediction

    from hevi.api.main import app
    from hevi.api.routers.creative import get_assist_service

    svc = _mock_assist()
    svc.predict_story = AsyncMock(  # type: ignore[method-assign]
        return_value=StoryPrediction(
            forward=[TimePrediction(seconds=3, description="hero runs")], backward=[]
        )
    )
    app.dependency_overrides[get_assist_service] = lambda: svc
    resp = await client.post(
        "/api/creative/story-predict",
        json={"reference_image": "/tmp/frame.png", "direction": "forward"},
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["forward"][0]["seconds"] == 3


@pytest.mark.asyncio
async def test_api_multi_angle(client: Any) -> None:
    from oprim.multi_angle import MultiAngleResult

    from hevi.api.main import app
    from hevi.api.routers.creative import get_assist_service

    svc = _mock_assist()
    svc.gen_multi_angle = AsyncMock(  # type: ignore[method-assign]
        return_value=MultiAngleResult(
            angle_prompts={"front": "fp"}, subject_description="car"
        )
    )
    app.dependency_overrides[get_assist_service] = lambda: svc
    resp = await client.post(
        "/api/creative/multi-angle",
        json={"subject_description": "red car"},
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["angle_prompts"]["front"] == "fp"


@pytest.mark.asyncio
async def test_api_transition(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.creative import get_assist_service

    svc = _mock_assist()
    svc.make_transition = AsyncMock(  # type: ignore[method-assign]
        return_value=Path("/tmp/out.mp4")
    )
    app.dependency_overrides[get_assist_service] = lambda: svc
    resp = await client.post(
        "/api/creative/transition",
        json={
            "first_frame": "/tmp/a.png",
            "last_frame": "/tmp/b.png",
            "duration_s": 3.0,
            "video_provider": "wan22_local",
            "output_path": "/tmp/out.mp4",
        },
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["output_path"] == "/tmp/out.mp4"


@pytest.mark.asyncio
async def test_api_element_edit(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.creative import get_assist_service

    svc = _mock_assist()
    svc.edit_video_elements = AsyncMock(  # type: ignore[method-assign]
        return_value=[{"type": "title", "text": "New"}]
    )
    app.dependency_overrides[get_assist_service] = lambda: svc
    resp = await client.post(
        "/api/creative/element-edit",
        json={
            "elements": [{"type": "title", "text": "Old"}],
            "operation": "replace",
            "target_index": 0,
            "replacement": {"type": "title", "text": "New"},
        },
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()[0]["text"] == "New"


@pytest.mark.asyncio
async def test_api_character_consistency(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.creative import get_workflow_service

    wf = _mock_workflow()
    wf.run_character_consistency = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            model_dump=MagicMock(
                return_value={
                    "consistency_score": 0.9,
                    "scene_variants": [],
                    "three_view": {},
                }
            )
        )
    )
    app.dependency_overrides[get_workflow_service] = lambda: wf
    resp = await client.post(
        "/api/creative/workflow/character-consistency",
        json={
            "portrait_image": "/tmp/face.png",
            "scene_descriptions": ["hero in forest"],
            "image_provider": "flux",
            "output_dir": "/tmp/out",
        },
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["consistency_score"] == 0.9


@pytest.mark.asyncio
async def test_api_storyboard_workflow(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.creative import get_workflow_service

    wf = _mock_workflow()
    wf.run_storyboard_workflow = AsyncMock(  # type: ignore[method-assign]
        return_value=MagicMock(
            model_dump=MagicMock(
                return_value={"shots": [], "grid_preview": None}
            )
        )
    )
    app.dependency_overrides[get_workflow_service] = lambda: wf
    resp = await client.post(
        "/api/creative/workflow/storyboard",
        json={
            "script": {
                "title": "T",
                "description": "",
                "scenes": [
                    {
                        "index": 0,
                        "narration": "",
                        "duration_s": 5.0,
                        "visual_description": "hero",
                    }
                ],
                "estimated_duration_s": 5.0,
            },
            "subjects": [],
            "image_provider": "flux",
            "output_dir": "/tmp/out",
            "grid_size": 9,
        },
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "shots" in resp.json()


@pytest.mark.asyncio
async def test_api_comic_to_animation(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.creative import get_workflow_service

    wf = _mock_workflow()
    wf.run_comic_to_animation = AsyncMock(  # type: ignore[method-assign]
        return_value=Path("/tmp/anim.mp4")
    )
    app.dependency_overrides[get_workflow_service] = lambda: wf
    resp = await client.post(
        "/api/creative/workflow/comic-to-animation",
        json={
            "comic_image": "/tmp/panel.png",
            "image_provider": "flux",
            "video_provider": "wan22_local",
            "output_path": "/tmp/anim.mp4",
        },
    )
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["output_path"] == "/tmp/anim.mp4"
