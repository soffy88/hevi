"""openshorts oskill：组合 ≥2 个 oprim 原子，不得引用 omodul。

对应 OpenShorts 三大核心能力的技能：
Clip Generator / AI Shorts / YouTube Studio
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.openshorts.oprim import (
    build_transcript_windows,
    clip_reframing_params,
    detect_scenes_gemini,
    extract_transcript_with_words,
    generate_script_from_description,
    generate_youtube_description,
    generate_youtube_thumbnail,
    generate_youtube_titles,
    make_clip_spec,
    plan_ai_short_actor,
    snap_clip_to_words_auto,
)
from hevi.openshorts.schemas import (
    AIActor,
    AICostMode,
    AICostPlan,
    AIScript,
    AIShortJob,
    ClipGeneratorJob,
    ClipSpec,
    PublishTicket,
    ReframingMode,
    SceneDetection,
    ViralMoment,
    WordTimestamp,
    YouTubeDescription,
    YouTubeStudioJob,
    YouTubeThumbnail,
    YouTubeTitle,
    make_ai_short_job,
    make_clip_generator_job,
    make_youtube_studio_job,
)

# ── Clip Generator 技能 ────────────────────────────────

def generate_clips(
    video_path: str,
    user_id: str = "",
    reframing: ReframingMode = ReframingMode.GENERAL,
    target_clips: int = 5,
    with_voiceover: bool = False,
    with_hook_text: bool = True,
    gemini_client: Any | None = None,
) -> ClipGeneratorJob:
    """Clip Generator 技能：完整流程。

    1. Extract transcript + word timestamps
    2. Detect scenes + viral moments (via Gemini)
    3. Build transcript windows aligned to segments
    4. Snap clip boundaries to word boundaries
    5. Generate ClipSpec list with reframe params + subtitles
    """
    # A local file takes the real execution path: transcription, viral scoring,
    # reframing and FFmpeg artifacts are all produced before the job is marked
    # completed.  URL planning remains available for callers that only want a
    # remote analysis plan and do not yet have a local media artifact.
    if Path(video_path).is_file():
        from hevi.openshorts.clip_engine import render_clip_batch

        output_dir = Path("output/openshorts") / Path(video_path).stem
        local_config = {
            "aspect_ratio": "9:16",
            "subtitle_path": "",
            "language": "",
        }
        rendered = render_clip_batch(
            video_path,
            output_dir=output_dir,
            target_clips=target_clips,
            config=local_config,
        )
        transcript_data = list(rendered.get("transcript") or [])
        clip_job = make_clip_generator_job(video_path, user_id)
        clip_job.reframing = reframing
        clip_job.target_clips = target_clips
        clip_job.with_voiceover = with_voiceover
        clip_job.with_hook_text = with_hook_text
        clip_job.transcript = {
            "segments": transcript_data,
            "text": " ".join(str(s.get("text") or "") for s in transcript_data),
        }
        clip_job.video_duration_s = max(
            (float(s.get("end") or 0.0) for s in transcript_data), default=0.0
        )
        clip_job.clips = [
            make_clip_spec(
                clip_index=int(item["index"]) - 1,
                start_s=float(item["start_s"]),
                end_s=float(item["end_s"]),
                headline=str(item["title"]),
                reframe_mode=reframing,
            )
            for item in rendered["clips"]
        ]
        for clip, item in zip(clip_job.clips, rendered["clips"], strict=True):
            clip.subtitle_text = str(item["title"])
            clip.effects = {"rendered_path": item["path"], "subtitle_path": item["subtitle_path"]}
        clip_job.status = "completed"
        return clip_job

    # 1. Transcript (remote/planning compatibility path)
    transcript = extract_transcript_with_words(video_path)
    video_duration = transcript.get("duration", 600.0)

    # 2. Scenes + viral moments(Gemini 可注入;默认走确定性 virality 打分)
    scenes = detect_scenes_gemini(
        transcript.get("text", ""),
        video_duration,
        viral_keywords=["important", "key", "trend", "viral"] if gemini_client else None
    )
    if not scenes:
        from hevi.ingest.video_transcript import TranscriptSegment
        from hevi.openshorts.virality import score_highlights

        segs = [
            TranscriptSegment(
                float(s.get("start") or 0.0),
                float(s.get("end") or 0.0),
                str(s.get("text") or ""),
            )
            for s in (transcript.get("segments") or [])
            if isinstance(s, dict) and s.get("text")
        ]
        highlights = score_highlights(segs, target_clips=target_clips)
        from hevi.openshorts.schemas import SceneDetection

        scenes = [
            SceneDetection(
                scene_id=f"h{i}",
                start_s=h.start_s,
                end_s=h.end_s,
                headline=h.title,
                viral_score=float(h.score),
            )
            for i, h in enumerate(highlights)
        ]

    # 3. Transcript windows
    build_transcript_windows(transcript, video_duration)

    # 4. Build ClipSpec list
    clip_job = make_clip_generator_job(video_path, user_id)
    clip_job.reframing = reframing
    clip_job.target_clips = target_clips
    clip_job.with_voiceover = with_voiceover
    clip_job.with_hook_text = with_hook_text
    clip_job.transcript = transcript
    clip_job.video_duration_s = video_duration

    # Select scenes with highest viral_score
    selected = sorted(scenes, key=lambda s: s.viral_score, reverse=True)[:target_clips]

    for i, scene in enumerate(selected):
        # Snap to word boundaries (placeholder: use scene bounds)
        start_s, end_s = snap_clip_to_words_auto(
            scene.start_s, scene.end_s,
            [WordTimestamp(word="", start_s=0) for _ in range(0)],  # 占位
            video_duration,
        )

        # Reframing params
        reframe_params = clip_reframing_params(reframing)

        clip = make_clip_spec(
            clip_index=i,
            start_s=start_s,
            end_s=end_s,
            headline=scene.headline or f"Key takeaway {i+1}",
            reframe_mode=reframing,
        )
        clip.reframe_params = reframe_params
        clip.subtitle_text = scene.headline

        if with_hook_text and i == 0:
            clip.effects = {
                "hook_text": f"Clip {i+1}: key takeaway",
                "visual_effect": "none",
                "transitions": ["cut"],
            }

        clip_job.clips.append(clip)

    clip_job.status = "planned"
    return clip_job


# ── AI Shorts 技能 ────────────────────────────────────

def generate_ai_short(
    description: str = "", url: str = "",
    user_id: str = "",
    cost_mode: AICostMode = AICostMode.LOW_COST,
    with_voiceover: bool = True,
    publish_platforms: list[str] | None = None,
) -> AIShortJob:
    """AI Shorts 同步兼容入口：只做可审查的计划，不伪造成品。

    1. Analyze (URL scrape or description)
    2. Script (Gemini viral script)
    3. Actor (Flux 2 Pro / gallery)
    4. Voice (ElevenLabs TTS)
    5. Video (Hailuo 2.3 Fast + VEED Lipsync)
    6. B-roll (Flux 2 Pro + Ken Burns)
    7. Composite (FFmpeg)
    8. Publish (Upload-Post)
    """
    job = make_ai_short_job(description=description, url=url, user_id=user_id)
    job.cost_plan.mode = cost_mode
    job.publish_platforms = publish_platforms or []
    if description.strip():
        job.script = generate_script_from_description(description, cost_mode)
        job.actor = plan_ai_short_actor(description, cost_mode)
    job.status = "blocked"
    job.error = (
        "同步入口只生成计划；要执行真实 AI Shorts，请调用异步 execute_ai_short，"
        "并提供 talking_head/video provider 或已存在的 talking_head_path。"
    )
    return job


def create_publish_tickets(
    job: AIShortJob | YouTubeStudioJob,
    platforms: list[str],
) -> list[PublishTicket]:
    """创建社交分发交接单。"""
    if isinstance(job, AIShortJob):
        media_path = job.composite_path
        title = job.script.hook
        desc = job.script.problem + " " + job.script.solution
    else:  # YouTubeStudioJob
        media_path = job.video_path
        title = job.selected_title
        desc = job.description.text

    tickets = []
    for platform in platforms:
        tickets.append(PublishTicket(
            platform=platform,
            media_path=media_path,
            title=title,
            description=desc,
        ))
    return tickets


# ── YouTube Studio 技能 ────────────────────────────────

def generate_youtube_package(
    video_path: str,
    user_id: str = "",
    source_title: str = "",
    source_description: str = "",
    target_titles: int = 10,
) -> YouTubeStudioJob:
    """YouTube Studio 技能：生成完整 SEO 包。

    1. AI 标题 (10 选项)
    2. AI 缩略图 (face overlay)
    3. AI 描述 + 章节
    """
    job = make_youtube_studio_job(video_path, user_id)
    job.source_title = source_title
    job.source_description = source_description

    # 1. Titles
    job.titles = generate_youtube_titles(
        source_title or source_description, target_titles
    )
    # Auto-select highest viral_score
    if job.titles:
        job.selected_title = max(job.titles, key=lambda t: t.viral_score).title

    # 2. Thumbnail: only a verified local frame is a generated thumbnail.
    job.thumbnail = generate_youtube_thumbnail(video_path)

    # 3. Description
    job.description = generate_youtube_description(
        job.selected_title, source_description
    )

    job.status = "completed" if job.thumbnail.path else "partial"
    return job


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    # Clip Generator
    "generate_clips",
    # AI Shorts
    "generate_ai_short", "create_publish_tickets",
    # YouTube Studio
    "generate_youtube_package",
]
