"""参考视频分析入口 —— 粘贴视频 → 拆解节奏/场景/风格 → 输出 2-3 个差异化概念。

对标 OpenMontage 的"Start From A Video You Already Love"工作流。
架构文档 §5.3.7:参考视频/图片 → VLM 拆解调色/光线/运镜/节奏 → 生成 StylePack 草稿。

流程:
    1. 转录(transcribe) → 提取对白/旁白文本
    2. 场景检测(scene_detect) → 切分场景 + 提取关键帧
    3. 节奏分析(pacing) → 镜头时长分布、切换频率
    4. 风格提取(style_extract) → VLM 分析关键帧,提炼视觉语言
    5. 概念生成(concept_gen) → 基于分析结果,产出 2-3 个差异化创作方向

用法:
    analysis = await analyze_reference_video(
        Path("ref.mp4"), output_dir=Path("output/ref_analysis"),
    )
    print(analysis.pacing.avg_shot_duration_s)  # 平均镜头时长
    print(analysis.style.palette)               # 主色调
    print(analysis.concepts[0].title)           # 第一个创作概念
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.analysis.scene_detect import Scene, detect_scenes
from hevi.analysis.transcribe import Transcript, transcribe_video

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────────────

@dataclass
class Pacing:
    total_duration_s: float
    scene_count: int
    avg_shot_duration_s: float
    median_shot_duration_s: float
    min_shot_duration_s: float
    max_shot_duration_s: float
    cuts_per_minute: float
    pacing_category: str  # "slow" / "medium" / "fast" / "rapid"


@dataclass
class StyleAnalysis:
    palette: list[str]           # 主色调 hex 列表
    lighting: str                # "natural" / "studio" / "golden_hour" / "neon" / ...
    color_temperature: str       # "warm" / "cool" / "neutral"
    saturation: str              # "high" / "medium" / "low" / "desaturated"
    camera_motion: list[str]     # 运镜风格列表 ["slow_pan", "static", "handheld"]
    composition_style: str       # "centered" / "rule_of_thirds" / "dynamic"
    visual_mood: str             # "cinematic" / "documentary" / "dreamy" / "energetic"
    aspect_ratio: str            # "16:9" / "9:16" / "1:1" / "21:9"
    notes: str = ""


@dataclass
class Concept:
    title: str
    description: str
    style_direction: str         # 视觉方向描述
    pacing_match: str            # 建议的节奏匹配
    estimated_cost_usd: float    # 预估成本
    differentiation: str         # 与参考的差异点


@dataclass
class ReferenceAnalysis:
    video_path: Path
    transcript: Transcript | None
    scenes: list[Scene]
    pacing: Pacing
    style: StyleAnalysis
    concepts: list[Concept] = field(default_factory=list)
    keyframes_dir: Path | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


# ── 主入口 ────────────────────────────────────────────────────────────────────

async def analyze_reference_video(
    video_path: Path,
    output_dir: Path,
    *,
    generate_concepts: bool = True,
    llm: Any = None,
) -> ReferenceAnalysis:
    """分析参考视频,输出结构化分析报告。

    Args:
        video_path: 参考视频路径(本地文件或 URL)
        output_dir: 输出目录
        generate_concepts: 是否生成创作概念(需要 LLM)
        llm: LLM 调用函数(可选,不传则跳过概念生成)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 如果是 URL,先下载
    local_path = await _ensure_local(video_path, output_dir)

    # 并行:转录 + 场景检测
    keyframes_dir = output_dir / "keyframes"
    transcript_task = asyncio.to_thread(
        transcribe_video, local_path, output_dir / "transcript",
    )
    scenes_task = asyncio.to_thread(
        detect_scenes, local_path, keyframes_dir, extract_keyframes=True,
    )
    transcript, scenes = await asyncio.gather(transcript_task, scenes_task)

    # 节奏分析(纯计算,不需要模型)
    pacing = _analyze_pacing(scenes, transcript)

    # 风格提取(用关键帧 + VLM,无 VLM 则用确定性启发式)
    style = await _extract_style(keyframes_dir, scenes, llm=llm)

    # 概念生成(需要 LLM)
    concepts = []
    if generate_concepts and llm:
        concepts = await _generate_concepts(transcript, pacing, style, llm=llm)

    analysis = ReferenceAnalysis(
        video_path=local_path,
        transcript=transcript,
        scenes=scenes,
        pacing=pacing,
        style=style,
        concepts=concepts,
        keyframes_dir=keyframes_dir,
    )

    # 持久化分析报告
    _save_report(analysis, output_dir)
    return analysis


# ── 内部实现 ──────────────────────────────────────────────────────────────────

async def _ensure_local(video_path: Path, output_dir: Path) -> Path:
    """确保视频在本地。如果是 URL 则下载。"""
    path_str = str(video_path)
    if path_str.startswith(("http://", "https://", "www.")):
        local = output_dir / "reference_input.mp4"
        if not local.exists():
            import subprocess
            subprocess.run(
                ["yt-dlp", "-o", str(local), "--no-playlist", path_str],
                timeout=120,
            )
            if not local.exists():
                # yt-dlp 失败回退 curl
                subprocess.run(
                    ["curl", "-sL", "-o", str(local), path_str],
                    timeout=120,
                )
        return local
    return Path(video_path)


def _analyze_pacing(scenes: list[Scene], transcript: Transcript | None) -> Pacing:
    """从场景列表分析节奏。"""
    if not scenes:
        return Pacing(
            total_duration_s=0, scene_count=0,
            avg_shot_duration_s=0, median_shot_duration_s=0,
            min_shot_duration_s=0, max_shot_duration_s=0,
            cuts_per_minute=0, pacing_category="unknown",
        )

    durations = [s.duration_s for s in scenes if s.duration_s > 0]
    total = sum(durations)
    sorted_d = sorted(durations)
    median = sorted_d[len(sorted_d) // 2] if sorted_d else 0
    avg = total / len(durations) if durations else 0
    cpm = (len(scenes) / (total / 60)) if total > 0 else 0

    if avg > 8:
        category = "slow"
    elif avg > 4:
        category = "medium"
    elif avg > 2:
        category = "fast"
    else:
        category = "rapid"

    return Pacing(
        total_duration_s=total,
        scene_count=len(scenes),
        avg_shot_duration_s=round(avg, 2),
        median_shot_duration_s=round(median, 2),
        min_shot_duration_s=round(min(durations), 2) if durations else 0,
        max_shot_duration_s=round(max(durations), 2) if durations else 0,
        cuts_per_minute=round(cpm, 1),
        pacing_category=category,
    )


async def _extract_style(
    keyframes_dir: Path,
    scenes: list[Scene],
    *,
    llm: Any = None,
) -> StyleAnalysis:
    """提取视觉风格。有 VLM 则用 VLM 分析关键帧,否则用启发式。"""
    keyframes = sorted(keyframes_dir.glob("*.jpg")) if keyframes_dir.exists() else []

    if llm and keyframes:
        return await _vlm_style_extract(llm, keyframes)

    # 启发式回退:从关键帧统计信息推断
    return _heuristic_style(keyframes, scenes)


async def _vlm_style_extract(llm: Any, keyframes: list[Path]) -> StyleAnalysis:
    """用 VLM 分析关键帧提取风格。"""
    # 选取最多 6 个均匀分布的关键帧
    step = max(1, len(keyframes) // 6)
    sample = keyframes[::step][:6]

    prompt = (
        "Analyze these video frames and extract the visual style. "
        "Return JSON with these fields:\n"
        '{"palette": ["#hex1"], "lighting": "natural|studio|golden_hour|neon", '
        '"color_temperature": "warm|cool|neutral", '
        '"saturation": "high|medium|low|desaturated", '
        '"camera_motion": ["static", "slow_pan"], '
        '"composition_style": "centered|rule_of_thirds|dynamic", '
        '"visual_mood": "cinematic|documentary|dreamy|energetic", '
        '"aspect_ratio": "16:9", "notes": "..."}'
    )

    try:
        response = await llm(prompt, images=[str(k) for k in sample])
        data = json.loads(response) if isinstance(response, str) else response
    except Exception as e:
        logger.warning("VLM style extraction failed: %s, falling back to heuristic", e)
        return _heuristic_style(keyframes, [])

    return StyleAnalysis(
        palette=data.get("palette", ["#333333"]),
        lighting=data.get("lighting", "natural"),
        color_temperature=data.get("color_temperature", "neutral"),
        saturation=data.get("saturation", "medium"),
        camera_motion=data.get("camera_motion", ["static"]),
        composition_style=data.get("composition_style", "centered"),
        visual_mood=data.get("visual_mood", "cinematic"),
        aspect_ratio=data.get("aspect_ratio", "16:9"),
        notes=data.get("notes", ""),
    )


def _heuristic_style(keyframes: list[Path], scenes: list[Scene]) -> StyleAnalysis:
    """启发式风格推断(无 VLM 回退)。"""
    return StyleAnalysis(
        palette=["#333333", "#666666", "#999999"],
        lighting="natural",
        color_temperature="neutral",
        saturation="medium",
        camera_motion=["static"],
        composition_style="centered",
        visual_mood="cinematic",
        aspect_ratio="16:9",
        notes="Heuristic analysis (no VLM available). Provide LLM for richer style extraction.",
    )


async def _generate_concepts(
    transcript: Transcript | None,
    pacing: Pacing,
    style: StyleAnalysis,
    *,
    llm: Any,
) -> list[Concept]:
    """基于分析结果生成 2-3 个差异化创作概念。"""
    pacing_line = (
        f"- Pacing: {pacing.pacing_category} "
        f"({pacing.avg_shot_duration_s}s avg, {pacing.cuts_per_minute} cuts/min)"
    )
    style_line = (
        f"- Style: {style.visual_mood}, {style.lighting} lighting, "
        f"{style.color_temperature} tone"
    )
    palette_line = f"- Palette: {', '.join(style.palette[:5])}"
    transcript_preview = (
        transcript.full_text[:200] if transcript else "No speech"
    )
    prompt = (
        f"Based on this reference video analysis:\n"
        f"{pacing_line}\n{style_line}\n{palette_line}\n"
        f"- Transcript preview: {transcript_preview}\n\n"
        "Generate 3 differentiated video concepts that match this style "
        "but with different topics. For each, return JSON: "
        '[{"title": "...", "description": "...", '
        '"style_direction": "...", '
        '"pacing_match": "slow|medium|fast", '
        '"estimated_cost_usd": 1.5, '
        '"differentiation": "..."}]'
    )

    try:
        response = await llm(prompt)
        data = json.loads(response) if isinstance(response, str) else response
        return [
            Concept(
                title=c.get("title", f"Concept {i+1}"),
                description=c.get("description", ""),
                style_direction=c.get("style_direction", ""),
                pacing_match=c.get("pacing_match", "medium"),
                estimated_cost_usd=c.get("estimated_cost_usd", 2.0),
                differentiation=c.get("differentiation", ""),
            )
            for i, c in enumerate(data if isinstance(data, list) else [])
        ]
    except Exception as e:
        logger.warning("Concept generation failed: %s", e)
        return []


def _save_report(analysis: ReferenceAnalysis, output_dir: Path) -> None:
    """保存分析报告为 JSON。"""
    report = {
        "video": str(analysis.video_path),
        "pacing": {
            "total_duration_s": analysis.pacing.total_duration_s,
            "scene_count": analysis.pacing.scene_count,
            "avg_shot_duration_s": analysis.pacing.avg_shot_duration_s,
            "cuts_per_minute": analysis.pacing.cuts_per_minute,
            "category": analysis.pacing.pacing_category,
        },
        "style": {
            "palette": analysis.style.palette,
            "lighting": analysis.style.lighting,
            "color_temperature": analysis.style.color_temperature,
            "saturation": analysis.style.saturation,
            "camera_motion": analysis.style.camera_motion,
            "visual_mood": analysis.style.visual_mood,
            "aspect_ratio": analysis.style.aspect_ratio,
        },
        "transcript_preview": analysis.transcript.full_text[:500] if analysis.transcript else None,
        "concepts": [
            {"title": c.title, "description": c.description, "cost_usd": c.estimated_cost_usd}
            for c in analysis.concepts
        ],
        "scenes_count": len(analysis.scenes),
    }
    report_path = output_dir / "analysis_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    logger.info("Reference analysis saved to %s", report_path)
