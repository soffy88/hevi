"""MCP tools: 9 creative assists — wraps P11.B AssistService + WorkflowService."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obase.mcp_server import SkillDef
from oskill._schemas import Script, SubjectRef

from hevi.creative.assist_service import AssistService
from hevi.creative.workflow_service import WorkflowService
from hevi.mcp.schemas import (
    CHARACTER_CONSISTENCY_INPUT,
    CHARACTER_CONSISTENCY_OUTPUT,
    COMIC_TO_ANIMATION_INPUT,
    COMIC_TO_ANIMATION_OUTPUT,
    ELEMENT_EDIT_INPUT,
    ELEMENT_EDIT_OUTPUT,
    MAKE_TRANSITION_INPUT,
    MAKE_TRANSITION_OUTPUT,
    MULTI_ANGLE_INPUT,
    MULTI_ANGLE_OUTPUT,
    PREDICT_STORY_INPUT,
    PREDICT_STORY_OUTPUT,
    STORYBOARD_INPUT,
    STORYBOARD_OUTPUT,
    STORYBOARD_WORKFLOW_INPUT,
    STORYBOARD_WORKFLOW_OUTPUT,
    THREE_VIEW_INPUT,
    THREE_VIEW_OUTPUT,
)


def build_creative_skills(
    assist_svc: AssistService | None = None,
    workflow_svc: WorkflowService | None = None,
) -> list[SkillDef]:
    _assist = assist_svc if assist_svc is not None else AssistService()
    _workflow = workflow_svc if workflow_svc is not None else WorkflowService()

    # ── Assist handlers ───────────────────────────────────────────────────────

    async def _three_view(args: dict[str, Any]) -> dict[str, Any]:
        result: Any = await _assist.gen_three_view(
            character_description=args["character_description"],
            style=args.get("style", "realistic"),
        )
        out: dict[str, Any] = result.model_dump()
        return out

    async def _storyboard(args: dict[str, Any]) -> dict[str, Any]:
        result: Any = await _assist.gen_storyboard(
            script_text=args["script_text"],
            shots=args.get("shots", 6),
        )
        out: dict[str, Any] = result.model_dump()
        return out

    async def _predict_story(args: dict[str, Any]) -> dict[str, Any]:
        result: Any = await _assist.predict_story(
            reference_image=Path(args["reference_image"]),
            direction=args["direction"],
            prediction_points=args.get("prediction_points", 3),
        )
        out: dict[str, Any] = result.model_dump()
        return out

    async def _multi_angle(args: dict[str, Any]) -> dict[str, Any]:
        result: Any = await _assist.gen_multi_angle(
            subject_description=args["subject_description"],
            angles=args.get("angles", ["front", "side", "top"]),
        )
        out: dict[str, Any] = result.model_dump()
        return out

    async def _make_transition(args: dict[str, Any]) -> dict[str, Any]:
        result: Any = await _assist.make_transition(
            first_frame=Path(args["first_frame"]),
            last_frame=Path(args["last_frame"]),
            duration_s=float(args.get("duration_s", 3.0)),
            video_provider=args["video_provider"],
            output_path=Path(args["output_path"]),
        )
        return {"output_path": str(result)}

    async def _element_edit(args: dict[str, Any]) -> dict[str, Any]:
        result: list[dict[str, Any]] = await _assist.edit_video_elements(
            elements=args["elements"],
            operation=args["operation"],
            target_index=int(args["target_index"]),
            replacement=args.get("replacement", {}),
        )
        return {"elements": result}

    # ── Workflow handlers ─────────────────────────────────────────────────────

    async def _character_consistency(args: dict[str, Any]) -> dict[str, Any]:
        result: Any = await _workflow.run_character_consistency(
            portrait_image=Path(args["portrait_image"]),
            scene_descriptions=args["scene_descriptions"],
            image_provider=args["image_provider"],
            output_dir=Path(args.get("output_dir", "/tmp/hevi_cc")),
        )
        out: dict[str, Any] = result.model_dump()
        return out

    async def _storyboard_workflow(args: dict[str, Any]) -> dict[str, Any]:
        script = Script.model_validate(args["script"])
        subjects = [SubjectRef.model_validate(s) for s in args.get("subjects", [])]
        result: Any = await _workflow.run_storyboard_workflow(
            script=script,
            subjects=subjects,
            image_provider=args["image_provider"],
            output_dir=Path(args.get("output_dir", "/tmp/hevi_sb")),
            grid_size=args.get("grid_size"),
            style=args.get("style"),
            lighting=args.get("lighting"),
        )
        out: dict[str, Any] = result.model_dump()
        return out

    async def _comic_to_animation(args: dict[str, Any]) -> dict[str, Any]:
        result: Any = await _workflow.run_comic_to_animation(
            comic_image=Path(args["comic_image"]),
            image_provider=args["image_provider"],
            video_provider=args["video_provider"],
            output_path=Path(args.get("output_path", "/tmp/hevi_comic.mp4")),
        )
        return {"output_path": str(result)}

    return [
        SkillDef(
            name="hevi.create_three_view",
            description="生成角色三视图提示词(正/侧/背)",
            input_schema=THREE_VIEW_INPUT,
            output_schema=THREE_VIEW_OUTPUT,
            handler=_three_view,
        ),
        SkillDef(
            name="hevi.gen_storyboard",
            description="生成分镜网格提示词",
            input_schema=STORYBOARD_INPUT,
            output_schema=STORYBOARD_OUTPUT,
            handler=_storyboard,
        ),
        SkillDef(
            name="hevi.predict_story",
            description="基于参考图像预测剧情走向",
            input_schema=PREDICT_STORY_INPUT,
            output_schema=PREDICT_STORY_OUTPUT,
            handler=_predict_story,
        ),
        SkillDef(
            name="hevi.gen_multi_angle",
            description="生成主体多角度提示词",
            input_schema=MULTI_ANGLE_INPUT,
            output_schema=MULTI_ANGLE_OUTPUT,
            handler=_multi_angle,
        ),
        SkillDef(
            name="hevi.make_transition",
            description="首尾帧过渡视频生成",
            input_schema=MAKE_TRANSITION_INPUT,
            output_schema=MAKE_TRANSITION_OUTPUT,
            handler=_make_transition,
        ),
        SkillDef(
            name="hevi.edit_video_elements",
            description="编辑视频元素列表(插入/替换/删除)",
            input_schema=ELEMENT_EDIT_INPUT,
            output_schema=ELEMENT_EDIT_OUTPUT,
            handler=_element_edit,
        ),
        SkillDef(
            name="hevi.run_character_consistency",
            description="角色一致性工作流：多场景保持人物一致",
            input_schema=CHARACTER_CONSISTENCY_INPUT,
            output_schema=CHARACTER_CONSISTENCY_OUTPUT,
            handler=_character_consistency,
        ),
        SkillDef(
            name="hevi.run_storyboard_workflow",
            description="多镜头分镜工作流：脚本到分镜网格",
            input_schema=STORYBOARD_WORKFLOW_INPUT,
            output_schema=STORYBOARD_WORKFLOW_OUTPUT,
            handler=_storyboard_workflow,
        ),
        SkillDef(
            name="hevi.run_comic_to_animation",
            description="漫画转动画工作流",
            input_schema=COMIC_TO_ANIMATION_INPUT,
            output_schema=COMIC_TO_ANIMATION_OUTPUT,
            handler=_comic_to_animation,
        ),
    ]
