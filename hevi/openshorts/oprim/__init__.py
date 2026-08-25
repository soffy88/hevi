"""openshorts oprim：无状态原子，不得引用 oskill/omodul。

对应 OpenShorts 三大核心能力的原子实现：
Clip Generator / AI Shorts / YouTube Studio
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
    YouTubeChapter,
    YouTubeDescription,
    YouTubeStudioJob,
    YouTubeThumbnail,
    YouTubeTitle,
    make_ai_short_job,
    make_clip_generator_job,
    make_youtube_studio_job,
)

# ── Clip Generator 原子 ────────────────────────────────

def clip_reframing_params(
    mode: ReframingMode,
    source_w: int = 1920, source_h: int = 1080,
) -> dict[str, Any]:
    """计算 9:16 重构参数（对应 OpenShorts 三种布局模式）。"""
    _target_w, _target_h = 1080, 1920  # 9:16
    
    if mode == ReframingMode.TRACK:
        # 面部跟踪模式：保持主要面部在中心，动态跟踪
        return {
            "method": "face_tracking",
            "crop": "center_dynamic",
            "confidence": 0.85,
        }
    if mode == ReframingMode.SPLIT:
        # 两位说话人叠加：每位获得半帧
        return {
            "method": "split_layout",
            "layouts": ["left_half", "right_half"],
            "tightness": 0.8,
            "separation_ratio": 0.20,
        }
    # GENERAL
    # 模糊背景 + 中心主体
    return {
        "method": "general_reframe",
        "crop_ratio": 0.8,
        "blur_background": True,
    }


def detect_scenes_gemini(
    transcript_text: str, video_duration: float,
    viral_keywords: list[str] | None = None
) -> list[SceneDetection]:
    """使用 Gemini 识别场景 + 病毒时刻。

    OpenShorts 使用 Gemini 3.5 Flash 分析转录本，
    返回 3-15 个带 viral_score 的片段。
    (实际实现由 Gemini API 调用)
    """
    # 占位：基础场景检测
    scenes: list[SceneDetection] = []
    # TODO: 集成 Gemini 返回
    return scenes


def extract_transcript_with_words(video_path: str) -> dict[str, Any]:
    """使用 faster-whisper 提取转录本 + 词级时间戳。

    OpenShorts 使用 faster-whisper，返回带 word-level timestamps 的 segments。
    (实际实现由 subprocess 调用 faster-whisper)
    """
    # 占位：返回空结构
    return {"segments": [], "text": ""}


def snap_clip_to_words_auto(
    start_s: float, end_s: float,
    words: list[WordTimestamp],
    video_duration: float,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
) -> tuple[float, float]:
    """将 Gemini 提出的 clip boundaries snap 到真实的 word boundaries。

    OpenShorts clip_selection.py 中的 snap_clip_to_words 逻辑。
    """
    original = (round(float(start_s), 3), round(float(end_s), 3))
    if not words:
        return original

    starts = [float(w.start_s) for w in words]
    ends = [float(w.end_s) for w in words]

    # START: snap to nearest word start + lead into silence
    new_start = float(start_s)
    candidates = [s for s in starts if abs(s - new_start) <= 1.5]
    if candidates:
        word_start = min(candidates, key=lambda s: abs(s - new_start))
        prev_ends = [e for e in ends if e <= word_start]
        if prev_ends:
            gap = max(0.0, word_start - max(prev_ends))
            lead = min(0.35, gap / 2)
        else:
            lead = 0.35
        new_start = max(0.0, word_start - lead)

    # END: snap to nearest word end + trail into silence
    new_end = float(end_s)
    candidates = [e for e in ends if abs(e - new_end) <= 1.5]
    if candidates:
        word_end = min(candidates, key=lambda e: abs(e - new_end))
        next_starts = [s for s in starts if s >= word_end]
        if next_starts:
            gap = max(0.0, min(next_starts) - word_end)
            tail = min(0.45, gap / 2)
        else:
            tail = 0.45
        new_end = min(float(video_duration), word_end + tail)

    # Repair duration bounds
    if new_end - new_start < min_duration:
        target = new_start + min_duration
        later = sorted([e for e in ends if e >= target])
        if later and later[0] - new_start <= max_duration:
            new_end = min(float(video_duration), later[0] + 0.2)
        else:
            return original
    if new_end - new_start > max_duration:
        target = new_start + max_duration
        earlier = [e for e in ends if new_start < e <= target]
        new_end = (max(earlier) + 0.2) if earlier else target
        new_end = min(new_end, new_start + max_duration, float(video_duration))

    if new_end <= new_start or new_end - new_start < min_duration:
        return original
    return (round(new_start, 3), round(new_end, 3))


def build_transcript_windows(
    transcript_result: dict[str, Any],
    video_duration: float,
    window_seconds: int = 90,
    overlap_seconds: int = 30,
) -> list[dict[str, Any]]:
    """Build transcript windows aligned to segment boundaries。

    OpenShorts build_transcript_windows 逻辑。
    """
    segments = transcript_result.get("segments", [])
    windows = []
    window_index = 1
    i = 0
    n = len(segments)

    while i < n:
        w_start = segments[i].get("start", 0) if segments else 0
        j = i
        while j + 1 < n and segments[j + 1].get("end", 0) - w_start <= window_seconds * 1.25:
            j += 1
            if segments[j].get("end", 0) - w_start >= window_seconds:
                break
        w_end = segments[j].get("end", video_duration) if segments else video_duration
        windows.append({
            "id": f"window_{window_index:03d}",
            "start": round(float(w_start), 3),
            "end": round(float(w_end), 3),
            "text": " ".join(str(seg.get("text", "")) for seg in segments[i:j + 1]),
        })
        window_index += 1
        if j >= n - 1:
            break
        target = w_end - overlap_seconds
        k = i + 1
        while k <= j and segments[k].get("start", 0) < target:
            k += 1
        i = max(k, i + 1)

    if not windows:
        windows.append({
            "id": "window_001",
            "start": 0.0,
            "end": round(float(video_duration), 3),
            "text": transcript_result.get("text", ""),
        })
    return windows


# ── AI Shorts 原子 ──────────────────────────────────────

def generate_script_from_description(
    description: str, cost_mode: AICostMode = AICostMode.LOW_COST
) -> AIScript:
    """从产品/主题描述生成 AI Shorts 脚本。

    OpenShorts AI Shorts pipeline：分析 → 脚本 → 演员 → 视频 → 分发。
    (实际实现由 Gemini + fal.ai/ ElevenLabs 调用)
    """
    # 解析描述，生成 hook/problem/solution/CTA 结构
    lines = [line.strip() for line in description.split('.') if line.strip()]
    
    hook = lines[0] if len(lines) > 0 else "为什么" + description[:20]
    problem = lines[1] if len(lines) > 1 else description[:50] + "的问题"
    solution = lines[2] if len(lines) > 2 else "了解" + description[:30] + "的解决方案"
    cta = lines[3] if len(lines) > 3 else "了解更多"
    
    # 生成 segments (每个 segment 约 8-10 秒)
    total_duration = 60.0
    segment_duration = total_duration / 4  # hook + problem + solution + cta
    segments = []
    for i in range(4):
        start = i * segment_duration
        end = min((i + 1) * segment_duration, total_duration)
        segments.append({
            "segment_id": i,
            "start_s": round(start, 3),
            "end_s": round(end, 3),
            "focus": ["hook", "problem", "solution", "cta"][i],
        })
    
    return AIScript(
        hook=hook,
        problem=problem,
        solution=solution,
        cta=cta,
        segments=segments,
        total_duration_s=total_duration,
    )


def plan_ai_short_actor(
    description: str, cost_mode: AICostMode = AICostMode.LOW_COST
) -> AIActor:
    """根据描述规划 AI Shorts 演员。

    返回 AIActor 实例，包含 provider、prompt、style 等。
    """
    # 根据描述和成本模式确定 provider 和 style
    if cost_mode == AICostMode.PREMIUM:
        provider = "kling_avatar_v2"
        style = "premium"
    else:
        provider = "flux_2_pro"
        style = "professional"
    
    return AIActor(
        provider=provider,
        prompt=description[:100] + "..." if len(description) > 100 else description,
        style=style,
    )


# ── YouTube Studio 原子 ────────────────────────────────

def generate_youtube_titles(
    video_content: str, target_count: int = 10
) -> list[YouTubeTitle]:
    """为现有视频生成 10 个带 viral_score 的 YouTube 标题。

    OpenShorts YouTube Studio 功能。
    """
    # 占位：返回模拟标题
    titles = []
    for i in range(target_count):
        viral_score = round(7.0 + (i * 0.3), 1)  # 7.0 - 9.9
        titles.append(YouTubeTitle(
            title=f"为什么 {video_content[:20]} 对每个人都很重要",
            viral_score=viral_score,
            reasoning=f"基于关键词 {video_content[:10]} 的病毒式分析",
        ))
    return titles


def generate_youtube_thumbnail(
    video_path: str, face_overlay: bool = True,
    style: str = "bold_text"
) -> YouTubeThumbnail:
    """生成 YouTube 缩略图（占位实现）。"""
    return YouTubeThumbnail(
        path="",  # 实际由 FFmpeg + Gemini 生成
        face_overlay=face_overlay,
        style=style,
    )


def generate_youtube_description(
    video_title: str, video_content: str, 
    auto_chapters: bool = True
) -> YouTubeDescription:
    """生成 YouTube 描述 + 章节。

    包含关键词丰富的文本、章节时间戳和 hashtags。
    """
    # 简单的章节生成（每 60 秒一个章节）
    chapters = []
    if auto_chapters:
        # 假设视频 600 秒 (10分钟)
        for i in range(10):
            start = i * 60
            end = min((i + 1) * 60, 600)
            chapters.append(YouTubeChapter(
                title=f"章节 {i+1}: 关键点 {i+1}",
                start_s=start,
                end_s=end,
            ))
    
    # 生成 hashtags (从视频标题提取关键词)
    hashtags = []
    if video_title:
        keywords = video_title.split()
        hashtags = [f"#{kw.replace(' ', '')}" for kw in keywords[:5]]
    
    return YouTubeDescription(
        text=f"了解{video_title}的更多信息。",
        chapters=chapters,
        hashtags=hashtags,
    )


# ── 辅助工厂 ───────────────────────────────────────────

def make_clip_spec(
    clip_index: int, start_s: float, end_s: float,
    headline: str, reframe_mode: ReframingMode = ReframingMode.GENERAL
) -> ClipSpec:
    """创建 ClipSpec 实例（便捷工厂）。"""
    return ClipSpec(
        clip_index=clip_index,
        start_time_s=start_s,
        end_time_s=end_s,
        duration_s=round(end_s - start_s, 3),
        headline=headline,
        reframe_mode=reframe_mode,
    )


# ── 导出 ───────────────────────────────────────────────

__all__ = [
    # Schema exports
    "ReframingMode", "ClipSpec", "ClipGeneratorJob", "AICostMode", "AICostPlan",
    "AIActor", "AIScript", "AIShortJob", "YouTubeTitle", "YouTubeThumbnail",
    "YouTubeChapter", "YouTubeDescription", "SceneDetection", "WordTimestamp",
    "ViralMoment", "PublishTicket",
    "make_clip_generator_job", "make_ai_short_job", "make_youtube_studio_job",
    "make_clip_spec",
    # Oprim functions
    "clip_reframing_params", "detect_scenes_gemini", "extract_transcript_with_words",
    "snap_clip_to_words_auto", "build_transcript_windows",
    "generate_script_from_description", "plan_ai_short_actor",
    "generate_youtube_titles", "generate_youtube_thumbnail",
    "generate_youtube_description",
]
