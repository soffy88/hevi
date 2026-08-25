"""magiviz oprim：无状态原子，不得引用 oskill/omodul。

Open-Magiviz 五步工作流原子实现：
1. 剧情生成 (story_generation)
2. 角色生成 (character_generation)
3. 分镜生成 (storyboard_generation)
4. 场景视频生成 (scene_video_generation)
5. 视频合成 (video_composition)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from hevi.magiviz.schemas import (
    CharacterDesign,
    JobStatus,
    MagivizJob,
    SceneVideo,
    Storyboard,
    StoryboardFrame,
    StoryDetails,
    StoryOutline,
    VideoAspectRatio,
    VideoModel,
    make_magiviz_job,
    make_story_outline,
)

# ── Step 1: AI 剧情生成 ───────────────────────────────


def generate_story_details(
    outline: StoryOutline,
    llm_model: str = "gpt-4o",
    temperature: float = 0.8,
) -> StoryDetails:
    """AI 生成详细剧情：场景分解、角色设定、导演指令、对话。

    对应 Open-Magiviz /api/ai/generate-story-details
    """
    # 占位：实际调用 LLM 生成
    characters = []
    for i, char_name in enumerate(["主角", "配角1", "配角2"]):
        characters.append(CharacterDesign(
            character_id=f"char_{i}",
            name=char_name,
            role=["protagonist", "supporting", "antagonist"][i % 3],
            visual_description=f"{char_name}的视觉特征",
            personality=f"{char_name}的性格特征",
        ))

    scenes = []
    for i in range(5):
        scenes.append({
            "scene_number": i + 1,
            "title": f"场景 {i+1}",
            "description": f"场景 {i+1} 的详细描述",
            "location": "室内/室外",
            "time": "白天/夜晚",
            "mood": "紧张/轻松",
        })

    dialogues = []
    for i in range(10):
        dialogues.append({
            "line_id": i,
            "speaker": characters[i % len(characters)].name,
            "text": f"台词 {i+1}",
            "emotion": "neutral",
        })

    return StoryDetails(
        outline=outline,
        characters=characters,
        scenes=scenes,
        dialogues=dialogues,
        director_notes=[
            "整体节奏：起承转合",
            "色调：前半段冷色调，后半段暖色调",
            "关键转折点在场景 3",
        ],
    )


# ── Step 2: 角色图像生成 ─────────────────────────────


def generate_character_image(
    character: CharacterDesign,
    model: str = "flux",
    style_prompt: str = "cinematic, detailed, consistent style",
) -> str:
    """生成角色参考图。

    对应 Open-Magiviz /api/ai/generate-character-image
    返回：生成的角色图像路径
    """
    # 占位：实际调用图像生成模型
    return f"/tmp/magiviz/characters/{character.character_id}.png"


def generate_all_characters(
    story_details: StoryDetails,
    model: str = "flux",
) -> StoryDetails:
    """并行生成所有角色图像。"""
    for character in story_details.characters:
        character.reference_image = generate_character_image(character, model)
    return story_details


# ── Step 3: 分镜图生成 ───────────────────────────────


def generate_storyboard_frame(
    scene: dict[str, Any],
    character_refs: dict[str, str],
    frame_number: int,
    model: str = "flux",
) -> StoryboardFrame:
    """生成单个分镜帧。

    对应 Open-Magiviz /api/ai/generate-storyboard-image
    """
    frame = StoryboardFrame(
        frame_id=f"frame_{frame_number}",
        scene_number=scene.get("scene_number", 1),
        shot_number=frame_number,
        description=scene.get("description", ""),
        composition="规则三分法构图",
        lighting="自然光/电影光",
        camera_angle="平视/仰视/俯视",
        camera_movement="固定/推拉/摇移",
        duration_s=scene.get("duration_s", 3.0),
        characters_present=scene.get("characters", []),
        visual_prompt=f"Storyboard frame for scene {scene.get('scene_number', 1)}",
    )
    return frame


def generate_storyboard(
    story_details: StoryDetails,
    aspect_ratio: VideoAspectRatio = VideoAspectRatio.LANDSCAPE_16_9,
) -> Storyboard:
    """生成完整分镜（并行处理每个场景）。"""
    character_refs = {c.name: c.reference_image for c in story_details.characters}
    frames = []
    frame_number = 1

    for scene in story_details.scenes:
        # 每个场景可能包含多个分镜
        shots = scene.get("shots", 3)
        for _shot in range(shots):
            frame = generate_storyboard_frame(scene, character_refs, frame_number)
            frames.append(frame)
            frame_number += 1

    total_duration = sum(f.duration_s for f in frames)
    return Storyboard(frames=frames, total_duration_s=total_duration, aspect_ratio=aspect_ratio)


# ── Step 4: 场景视频生成 ─────────────────────────────


def generate_scene_video(
    storyboard_frame: StoryboardFrame,
    model: VideoModel = VideoModel.WAN,
    seed: int = 0,
) -> SceneVideo:
    """生成单个场景视频。

    对应 Open-Magiviz /api/ai/generate-story-video
    """
    scene_video = SceneVideo(
        scene_id=storyboard_frame.frame_id,
        storyboard_frame_ids=[storyboard_frame.frame_id],
        video_model=model,
        video_path=f"/tmp/magiviz/scenes/{storyboard_frame.frame_id}.mp4",
        duration_s=storyboard_frame.duration_s,
        resolution="1920x1080",
        seed=seed,
        prompt=storyboard_frame.visual_prompt,
        negative_prompt="low quality, blurry, distorted",
    )
    return scene_video


def generate_scene_videos_parallel(
    storyboard: Storyboard,
    model: VideoModel = VideoModel.WAN,
) -> list[SceneVideo]:
    """并行生成所有场景视频。"""
    scene_videos = []
    for frame in storyboard.frames:
        scene_videos.append(generate_scene_video(frame, model))
    return scene_videos


# ── Step 5: 视频合成 ─────────────────────────────────


def compose_story_video(
    scene_videos: list[SceneVideo],
    output_path: str,
    add_transitions: bool = True,
    add_music: bool = True,
    music_path: str = "",
) -> str:
    """合成最终视频。

    对应 Open-Magiviz /api/ai/fal/compose-story-video
    使用 ffmpeg 拼接场景视频，添加转场、背景音乐、字幕
    """
    # 占位：实际使用 ffmpeg 合成
    return output_path


# ── 完整流水线 ───────────────────────────────────────


def run_full_pipeline(
    job: MagivizJob,
) -> MagivizJob:
    """运行完整的五步工作流。"""
    # Step 1: 剧情生成
    job.status = JobStatus.STORY_GENERATING
    job.story_details = generate_story_details(job.story_outline)

    # Step 2: 角色生成
    job.status = JobStatus.CHARACTER_GENERATING
    job.story_details = generate_all_characters(job.story_details)

    # Step 3: 分镜生成
    job.status = JobStatus.STORYBOARD_GENERATING
    job.storyboard = generate_storyboard(job.story_details, job.story_outline.aspect_ratio)

    # Step 4: 场景视频生成
    job.status = JobStatus.SCENES_GENERATING
    job.scene_videos = generate_scene_videos_parallel(job.storyboard)

    # Step 5: 视频合成
    job.status = JobStatus.COMPOSING
    job.final_video_path = compose_story_video(job.scene_videos, f"/tmp/magiviz/{job.job_id}_final.mp4")

    job.status = JobStatus.COMPLETED
    return job


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    "compose_story_video",
    "generate_all_characters",
    "generate_character_image",
    "generate_scene_video",
    "generate_scene_videos_parallel",
    "generate_story_details",
    "generate_storyboard",
    "generate_storyboard_frame",
    "run_full_pipeline",
]
