"""hevi 参考视频分析服务 - 转录/节奏/场景提取

P0: 解决 hevi 缺失的参考视频驱动能力
粘贴 YouTube/TikTok → 转录/节奏/场景分析 → 差异化概念
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, Field


@dataclass
class ReferenceAnalysisConfig:
    """参考视频分析配置"""
    whisper_endpoint: str = os.getenv("WHISPER_ENDPOINT", "http://localhost:9000")
    scene_detect_endpoint: str = os.getenv("SCENE_DETECT_ENDPOINT", "http://localhost:9001")
    clap_score_endpoint: str = os.getenv("CLAP_SCORE_ENDPOINT", "http://localhost:9002")


class TranscriptSegment(BaseModel):
    """转录片段"""
    start_s: float
    end_s: float
    text: str
    confidence: float | None = None


class RhythmAnalysis(BaseModel):
    """节奏分析"""
    total_duration_s: float
    shot_changes: list[float]  # timeline of shot boundaries
    beats_per_minute: float | None = None
    energy_curve: list[float] | None = None  # per-second energy


class SceneBreakdown(BaseModel):
    """场景分解"""
    scene_no: int
    start_s: float
    end_s: float
    duration_s: float
    description: str
    key_elements: list[str] = Field(default_factory=list)
    visual_style: str | None = None


class ConceptVariant(BaseModel):
    """差异化概念"""
    concept_id: str
    title: str
    pitch: str
    angle: str  # how it differs from the reference
    estimated_cost: float = 0.0
    reference_similarity: float = 0.0  # 0-1, how close to original


class ReferenceVideoAnalysis(BaseModel):
    """参考视频分析结果"""
    source_url: str
    transcript: list[TranscriptSegment]
    rhythm: RhythmAnalysis
    scenes: list[SceneBreakdown]
    key_visual_moments: list[dict[str, Any]] = Field(default_factory=list)
    concepts: list[ConceptVariant]
    metadata: dict[str, Any] = Field(default_factory=dict)


async def fetch_transcript(video_url: str) -> list[TranscriptSegment]:
    """从视频 URL 提取转录文本"""
    config = ReferenceAnalysisConfig()

    async with httpx.AsyncClient(timeout=300) as client:
        try:
            # Try faster-whisper service
            resp = await client.post(
                f"{config.whisper_endpoint}/transcribe",
                json={"url": video_url, "task": "transcribe", "language": "zh"},
            )
            resp.raise_for_status()
            data = resp.json()

            return [
                TranscriptSegment(
                    start_s=seg["start"],
                    end_s=seg["end"],
                    text=seg["text"],
                    confidence=seg.get("confidence"),
                )
                for seg in data.get("segments", [])
            ]
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            # Fallback: empty transcript
            return []


async def analyze_rhythm(video_url: str) -> RhythmAnalysis:
    """分析视频节奏"""
    config = ReferenceAnalysisConfig()

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(
                f"{config.scene_detect_endpoint}/rhythm",
                json={"url": video_url},
            )
            resp.raise_for_status()
            data = resp.json()

            return RhythmAnalysis(
                total_duration_s=data.get("duration", 0.0),
                shot_changes=data.get("shot_changes", []),
                beats_per_minute=data.get("bpm"),
                energy_curve=data.get("energy_curve"),
            )
        except Exception as e:
            logger.error(f"Rhythm analysis failed: {e}")
            return RhythmAnalysis(total_duration_s=0.0, shot_changes=[])


async def extract_scenes(video_url: str) -> list[SceneBreakdown]:
    """提取场景边界"""
    config = ReferenceAnalysisConfig()

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(
                f"{config.scene_detect_endpoint}/scenes",
                json={"url": video_url},
            )
            resp.raise_for_status()
            data = resp.json()

            return [
                SceneBreakdown(
                    scene_no=scene["no"],
                    start_s=scene["start"],
                    end_s=scene["end"],
                    duration_s=scene["end"] - scene["start"],
                    description=scene.get("description", ""),
                    key_elements=scene.get("elements", []),
                    visual_style=scene.get("style"),
                )
                for scene in data.get("scenes", [])
            ]
        except Exception as e:
            logger.error(f"Scene extraction failed: {e}")
            return []


async def generate_concepts(
    transcript: list[TranscriptSegment],
    rhythm: RhythmAnalysis,
    scenes: list[SceneBreakdown],
) -> list[ConceptVariant]:
    """基于分析结果生成 2-3 个差异化概念"""
    # TODO: 调用 hevi LLM 网关生成概念
    # 暂时返回占位结构
    return [
        ConceptVariant(
            concept_id="c1",
            title="参考视频同主题差异化视角",
            pitch="保持原视频核心信息，换一个叙事角度",
            angle="从对立观点切入，制造冲突张力",
            estimated_cost=50.0,
            reference_similarity=0.7,
        ),
        ConceptVariant(
            concept_id="c2",
            title="参照视频视觉风格重塑",
            pitch="保留节奏模式，更换视觉风格",
            angle="用动画/手绘风格重新呈现",
            estimated_cost=80.0,
            reference_similarity=0.4,
        ),
        ConceptVariant(
            concept_id="c3",
            title="参考视频扩写加长版",
            pitch="将短内容扩展为系列",
            angle="拆分为 3 集系列，每集独立钩子",
            estimated_cost=120.0,
            reference_similarity=0.6,
        ),
    ]


async def analyze_reference_video(url: str) -> ReferenceVideoAnalysis:
    """完整参考视频分析流程"""
    transcript = await fetch_transcript(url)
    rhythm = await analyze_rhythm(url)
    scenes = await extract_scenes(url)
    concepts = await generate_concepts(transcript, rhythm, scenes)

    return ReferenceVideoAnalysis(
        source_url=url,
        transcript=transcript,
        rhythm=rhythm,
        scenes=scenes,
        key_visual_moments=[],
        concepts=concepts,
        metadata={},
    )


__all__ = [
    "ConceptVariant",
    "ReferenceAnalysisConfig",
    "ReferenceVideoAnalysis",
    "RhythmAnalysis",
    "SceneBreakdown",
    "TranscriptSegment",
    "analyze_reference_video",
    "analyze_rhythm",
    "extract_scenes",
    "fetch_transcript",
    "generate_concepts",
]
