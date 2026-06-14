from __future__ import annotations

from typing import Any

ASSIST_REGISTRY: dict[str, dict[str, Any]] = {
    "three_view": {
        "name": "三视图生成",
        "inputs": ["character_description", "style"],
        "outputs": ["ThreeViewResult"],
        "providers": ["llm"],
        "kind": "oprim",
    },
    "storyboard": {
        "name": "分镜网格生成",
        "inputs": ["script_text", "shots"],
        "outputs": ["StoryboardGridResult"],
        "providers": ["llm"],
        "kind": "oprim",
    },
    "story_predict": {
        "name": "剧情预测",
        "inputs": ["reference_image", "direction", "prediction_points"],
        "outputs": ["StoryPrediction"],
        "providers": ["llm"],
        "kind": "oprim",
    },
    "multi_angle": {
        "name": "多角度提示生成",
        "inputs": ["subject_description", "angles"],
        "outputs": ["MultiAngleResult"],
        "providers": ["llm"],
        "kind": "oprim",
    },
    "transition": {
        "name": "首尾帧过渡",
        "inputs": ["first_frame", "last_frame", "duration_s", "video_provider"],
        "outputs": ["output_path"],
        "providers": ["image_to_video"],
        "kind": "oprim",
    },
    "element_edit": {
        "name": "视频元素编辑",
        "inputs": ["elements", "operation", "target_index", "replacement"],
        "outputs": ["list[dict]"],
        "providers": ["llm"],
        "kind": "oprim",
    },
    "character_consistency": {
        "name": "角色一致性工作流",
        "inputs": ["portrait_image", "scene_descriptions", "image_provider"],
        "outputs": ["CharacterConsistencyResult"],
        "providers": ["llm", "image_gen"],
        "kind": "oskill",
    },
    "storyboard_workflow": {
        "name": "多镜头分镜工作流",
        "inputs": ["script", "subjects", "image_provider", "grid_size", "style", "lighting"],
        "outputs": ["MultiShotStoryboard"],
        "providers": ["llm", "image_gen"],
        "kind": "oskill",
    },
    "comic_to_animation": {
        "name": "漫画转动画工作流",
        "inputs": ["comic_image", "image_provider", "video_provider"],
        "outputs": ["output_path"],
        "providers": ["llm", "image_gen", "image_to_video"],
        "kind": "oskill",
    },
}

ASSIST_NAMES: frozenset[str] = frozenset(ASSIST_REGISTRY)
