"""JSON schema constants for hevi MCP tools."""

from __future__ import annotations

from typing import Any


def _obj(
    props: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        s["required"] = required
    return s


# ── Video ─────────────────────────────────────────────────────────────────────

GENERATE_LONGVIDEO_INPUT = _obj(
    {
        "topic": {"type": "string", "description": "视频主题/提示词"},
        "duration_archetype": {
            "type": "string",
            "enum": ["short", "medium", "long"],
            "description": "时长档: short≈1-3min, medium≈3-8min, long≈8min+",
        },
        "video_provider": {"type": "string", "description": "视频生成 provider"},
        "audio_provider": {"type": "string", "description": "音频生成 provider"},
        "style": {"type": "string", "default": "cinematic"},
        "language": {"type": "string", "default": "zh"},
    },
    required=["topic", "duration_archetype", "video_provider", "audio_provider"],
)

GENERATE_LONGVIDEO_OUTPUT = _obj(
    {
        "video_path": {"type": "string"},
        "shots_count": {"type": "integer"},
        "status": {"type": "string"},
    }
)

# ── Creative assist ───────────────────────────────────────────────────────────

THREE_VIEW_INPUT = _obj(
    {
        "character_description": {"type": "string"},
        "style": {"type": "string", "default": "realistic"},
    },
    required=["character_description"],
)

THREE_VIEW_OUTPUT = _obj(
    {
        "front_view_prompt": {"type": "string"},
        "side_view_prompt": {"type": "string"},
        "back_view_prompt": {"type": "string"},
    }
)

STORYBOARD_INPUT = _obj(
    {
        "script_text": {"type": "string"},
        "shots": {"type": "integer", "default": 6},
    },
    required=["script_text"],
)

STORYBOARD_OUTPUT = _obj(
    {
        "grid_prompts": {"type": "array", "items": {"type": "string"}},
        "shot_count": {"type": "integer"},
    }
)

PREDICT_STORY_INPUT = _obj(
    {
        "reference_image": {"type": "string", "description": "本地图像文件路径"},
        "direction": {
            "type": "string",
            "enum": ["forward", "backward", "both"],
        },
        "prediction_points": {"type": "integer", "default": 3},
    },
    required=["reference_image", "direction"],
)

PREDICT_STORY_OUTPUT = _obj(
    {"predictions": {"type": "array", "items": {"type": "string"}}}
)

MULTI_ANGLE_INPUT = _obj(
    {
        "subject_description": {"type": "string"},
        "angles": {
            "type": "array",
            "items": {"type": "string"},
            "default": ["front", "side", "top"],
        },
    },
    required=["subject_description"],
)

MULTI_ANGLE_OUTPUT = _obj({"angle_prompts": {"type": "object"}})

MAKE_TRANSITION_INPUT = _obj(
    {
        "first_frame": {"type": "string", "description": "首帧图像路径"},
        "last_frame": {"type": "string", "description": "末帧图像路径"},
        "duration_s": {"type": "number", "default": 3.0},
        "video_provider": {"type": "string"},
        "output_path": {"type": "string"},
    },
    required=["first_frame", "last_frame", "video_provider", "output_path"],
)

MAKE_TRANSITION_OUTPUT = _obj({"output_path": {"type": "string"}})

ELEMENT_EDIT_INPUT = _obj(
    {
        "elements": {"type": "array", "items": {"type": "object"}},
        "operation": {"type": "string", "enum": ["insert", "replace", "delete"]},
        "target_index": {"type": "integer"},
        "replacement": {"type": "object"},
    },
    required=["elements", "operation", "target_index", "replacement"],
)

ELEMENT_EDIT_OUTPUT = _obj(
    {"elements": {"type": "array", "items": {"type": "object"}}}
)

# ── Creative workflow ─────────────────────────────────────────────────────────

CHARACTER_CONSISTENCY_INPUT = _obj(
    {
        "portrait_image": {"type": "string", "description": "人物肖像图像路径"},
        "scene_descriptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "场景描述列表",
        },
        "image_provider": {"type": "string"},
        "output_dir": {"type": "string", "default": "/tmp/hevi_cc"},
    },
    required=["portrait_image", "scene_descriptions", "image_provider"],
)

CHARACTER_CONSISTENCY_OUTPUT = _obj(
    {"scene_images": {"type": "array", "items": {"type": "string"}}}
)

STORYBOARD_WORKFLOW_INPUT = _obj(
    {
        "script": {
            "type": "object",
            "description": "Script对象(title/description/scenes/estimated_duration_s)",
        },
        "subjects": {
            "type": "array",
            "items": {"type": "object"},
            "description": "SubjectRef列表",
            "default": [],
        },
        "image_provider": {"type": "string"},
        "output_dir": {"type": "string", "default": "/tmp/hevi_sb"},
        "grid_size": {"type": "integer", "enum": [9, 25]},
        "style": {"type": "string"},
        "lighting": {"type": "string"},
    },
    required=["script", "image_provider"],
)

STORYBOARD_WORKFLOW_OUTPUT = _obj(
    {"shots": {"type": "array", "items": {"type": "object"}}}
)

COMIC_TO_ANIMATION_INPUT = _obj(
    {
        "comic_image": {"type": "string", "description": "漫画图像路径"},
        "image_provider": {"type": "string"},
        "video_provider": {"type": "string"},
        "output_path": {"type": "string", "default": "/tmp/hevi_comic.mp4"},
    },
    required=["comic_image", "image_provider", "video_provider"],
)

COMIC_TO_ANIMATION_OUTPUT = _obj({"output_path": {"type": "string"}})

# ── Subject ───────────────────────────────────────────────────────────────────

SUBJECT_CREATE_INPUT = _obj(
    {
        "name": {"type": "string"},
        "kind": {
            "type": "string",
            "enum": ["character", "portrait", "product", "scene"],
        },
        "description": {"type": "string", "default": ""},
        "reference_images": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
        },
        "user_id": {"type": "string"},
    },
    required=["name", "kind"],
)

SUBJECT_CREATE_OUTPUT = _obj(
    {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "kind": {"type": "string"},
    }
)

SUBJECT_SEARCH_INPUT = _obj(
    {
        "kind": {"type": "string"},
        "query": {"type": "string"},
        "user_id": {"type": "string"},
    }
)

SUBJECT_SEARCH_OUTPUT = _obj(
    {
        "subjects": {"type": "array", "items": {"type": "object"}},
        "count": {"type": "integer"},
    }
)

# ── Canvas ────────────────────────────────────────────────────────────────────

EXECUTE_CANVAS_INPUT = _obj(
    {
        "graph_id": {"type": "string", "description": "画布图 UUID"},
        "on_error": {
            "type": "string",
            "enum": ["rollback", "continue"],
            "default": "rollback",
        },
    },
    required=["graph_id"],
)

EXECUTE_CANVAS_OUTPUT = _obj(
    {
        "graph_id": {"type": "string"},
        "status": {"type": "string"},
        "node_count": {"type": "integer"},
        "results": {"type": "object"},
    }
)

# ── Capabilities ──────────────────────────────────────────────────────────────

LIST_CAPABILITIES_INPUT: dict[str, Any] = {"type": "object", "properties": {}}

LIST_CAPABILITIES_OUTPUT = _obj(
    {
        "capabilities": {"type": "object"},
        "count": {"type": "integer"},
    }
)
