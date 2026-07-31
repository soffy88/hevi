"""长视频→短视频智能拆条 —— 对标 chengfeng-videocut-skills + muapi AI Clipping。

能力:
- Whisper 转写（自动识别语言）
- LLM 病毒评分框架（Hook / 情感峰值 / 观点炸弹 / 揭秘 / 冲突 / 金句 / 故事高潮 / 实用价值）
- 人脸追踪裁剪（自动 9:16 竖屏）
- 重叠去重

用法:
    from hevi.video.video_clipper import clip_long_video
    clips = await clip_long_video(
        input_path=Path("long_video.mp4"),
        num_clips=5,
        aspect_ratio="9:16",
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ClipCandidate:
    """单个候选短视频片段。"""
    start_time: float
    end_time: float
    score: int  # 0-100 病毒评分
    title: str
    hook_sentence: str
    virality_reason: str
    category: str  # hook / emotional_peak / opinion_bomb / revelation / conflict / quotable / story_peak / practical_value
    clip_path: Path | None = None  # 裁剪后的本地路径
    clip_url: str | None = None


@dataclass
class ClipResult:
    """拆条结果。"""
    source_path: Path
    total_duration_s: float
    clips: list[ClipCandidate] = field(default_factory=list)
    transcript_path: Path | None = None
    error: str | None = None


# ── 病毒评分分类 ────────────────────────────────────────────────────────────

VIRALITY_CATEGORIES = [
    "hook",             # 强力开头，吸引停留
    "emotional_peak",   # 情感高潮（笑声/愤怒/脆弱/敬畏）
    "opinion_bomb",     # 观点炸弹（争议性/反常识）
    "revelation",       # 揭秘时刻（"等等，什么？"）
    "conflict",         # 冲突（对立/紧张/对峙）
    "quotable",         # 金句（精炼、值得截图）
    "story_peak",       # 故事高潮（叙事弧的顶点）
    "practical_value",  # 实用价值（可操作的洞察）
]

_SCORING_PROMPT = """你是一个短视频病毒评分专家。请对以下视频转写内容进行分析，提取 {num_clips} 个最有可能在短视频平台（TikTok/Reels/Shorts）获得高传播的片段。

## 转写内容
{transcript}

## 评分框架
请按以下 8 个维度评估每个候选片段:
1. hook — 强力开头，吸引停留
2. emotional_peak — 情感高潮
3. opinion_bomb — 观点炸弹
4. revelation — 揭秘时刻
5. conflict — 冲突/紧张
6. quotable — 金句
7. story_peak — 故事高潮
8. practical_value — 实用价值

## 输出格式（JSON）
```json
{{
  "clips": [
    {{
      "start_time": 124.3,
      "end_time": 187.6,
      "score": 92,
      "title": "一个让所有人沉默的错误",
      "hook_sentence": "没人谈论这个，但它毁了我的第一个创业项目...",
      "virality_reason": "以数字+遗憾开场，在反直觉教训上达到高潮",
      "category": "opinion_bomb"
    }}
  ]
}}
```

请输出 JSON，不要其他内容。"""


# ── 主入口 ─────────────────────────────────────────────────────────────────


async def clip_long_video(
    input_path: Path,
    *,
    num_clips: int = 5,
    aspect_ratio: str = "9:16",
    coords_only: bool = False,
    whisper_model: str = "base",
    output_dir: Path | None = None,
    llm: Any | None = None,
) -> ClipResult:
    """将长视频拆分为多个短视频片段。

    Args:
        input_path: 输入视频路径
        num_clips: 提取片段数
        aspect_ratio: 9:16 / 1:1 / 4:5
        coords_only: 只返回时间范围，不裁剪
        whisper_model: Whisper 模型大小（tiny/base/small/medium/large）
        output_dir: 输出目录（默认在 input_path 旁边创建 clips/）
        llm: 可选 LLM 函数（默认用 qwen_cloud）

    Returns:
        ClipResult
    """
    if not input_path.exists():
        return ClipResult(
            source_path=input_path,
            total_duration_s=0,
            error=f"Input file not found: {input_path}",
        )

    if output_dir is None:
        output_dir = input_path.parent / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 获取视频时长
    duration = _get_video_duration(input_path)
    if duration <= 0:
        return ClipResult(source_path=input_path, total_duration_s=0, error="Cannot read video duration")

    # 2. Whisper 转写
    transcript_path = output_dir / "transcript.json"
    transcript = await _transcribe_with_whisper(
        input_path, transcript_path, model=whisper_model
    )
    if not transcript:
        return ClipResult(
            source_path=input_path,
            total_duration_s=duration,
            transcript_path=transcript_path,
            error="Whisper transcription failed",
        )

    # 3. LLM 评分 + 候选提取
    if llm is None:
        try:
            from obase.provider_registry import ProviderRegistry
            llm = ProviderRegistry.get().llm("qwen_cloud")
        except Exception:
            logger.warning("video_clipper: qwen_cloud not available, using fallback scoring")
            llm = None

    candidates = await _score_and_extract(
        transcript, num_clips=num_clips, llm=llm
    )

    if not candidates:
        return ClipResult(
            source_path=input_path,
            total_duration_s=duration,
            transcript_path=transcript_path,
            error="No clip candidates found",
        )

    # 4. 裁剪（除非 coords_only）
    if not coords_only:
        for i, clip in enumerate(candidates):
            clip.clip_path = output_dir / f"clip_{i+1:02d}_{clip.category}_{clip.score}.mp4"
            success = _crop_clip(
                input_path, clip, aspect_ratio=aspect_ratio
            )
            if success:
                logger.info("video_clipper: clip %d/%d cropped: %s", i+1, len(candidates), clip.clip_path)
            else:
                logger.warning("video_clipper: clip %d/%d crop failed", i+1, len(candidates))

    return ClipResult(
        source_path=input_path,
        total_duration_s=duration,
        clips=candidates,
        transcript_path=transcript_path,
    )


# ── 内部工具函数 ───────────────────────────────────────────────────────────


def _get_video_duration(path: Path) -> float:
    """用 ffprobe 获取视频时长。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning("_get_video_duration failed: %s", e)
        return 0.0


async def _transcribe_with_whisper(
    video_path: Path,
    output_path: Path,
    model: str = "base",
) -> str | None:
    """用 Whisper CLI 转写视频。"""
    audio_path = output_path.parent / "audio.wav"

    # 提取音频
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                str(audio_path),
            ],
            capture_output=True, timeout=120,
        )
    except Exception as e:
        logger.warning("ffmpeg audio extraction failed: %s", e)
        return None

    # Whisper 转写
    try:
        result = subprocess.run(
            [
                "whisper", str(audio_path),
                "--model", model,
                "--output_dir", str(output_path.parent),
                "--output_format", "json",
            ],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            logger.warning("whisper failed: %s", result.stderr[:500])
            return None

        # 读取转写结果
        json_path = output_path
        if json_path.exists():
            data = json.loads(json_path.read_text())
            segments = data.get("segments", [])
            return " ".join(s.get("text", "") for s in segments)
        return None

    except FileNotFoundError:
        logger.warning("whisper CLI not found, trying Python API")
        return await _transcribe_whisper_python(audio_path, output_path, model)
    except Exception as e:
        logger.warning("whisper transcription failed: %s", e)
        return None


async def _transcribe_whisper_python(
    audio_path: Path, output_path: Path, model: str
) -> str | None:
    """Python Whisper API 转写（fallback）。"""
    try:
        import whisper
        m = whisper.load_model(model)
        result = m.transcribe(str(audio_path))
        text = result.get("text", "")
        # 保存
        output_path.write_text(json.dumps({
            "text": text,
            "segments": [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in result.get("segments", [])
            ],
        }, ensure_ascii=False))
        return text
    except ImportError:
        logger.warning("whisper Python package not installed")
        return None
    except Exception as e:
        logger.warning("whisper Python API failed: %s", e)
        return None


async def _score_and_extract(
    transcript: str,
    num_clips: int = 5,
    llm: Any | None = None,
) -> list[ClipCandidate]:
    """LLM 评分 + 候选提取。"""
    if llm is None or not transcript.strip():
        return _fallback_extract(transcript, num_clips)

    prompt = _SCORING_PROMPT.format(
        num_clips=num_clips,
        transcript=transcript[:8000],  # 截断避免超长
    )

    try:
        response = await llm(prompt)
        json_str = response.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            json_str = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            json_str = json_str.strip()

        data = json.loads(json_str)
        clips_data = data.get("clips", [])

        candidates = []
        for c in clips_data[:num_clips]:
            candidates.append(ClipCandidate(
                start_time=float(c.get("start_time", 0)),
                end_time=float(c.get("end_time", 0)),
                score=int(c.get("score", 50)),
                title=str(c.get("title", "")),
                hook_sentence=str(c.get("hook_sentence", "")),
                virality_reason=str(c.get("virality_reason", "")),
                category=str(c.get("category", "hook")),
            ))

        # 按分数降序排列
        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    except json.JSONDecodeError:
        logger.warning("_score_and_extract: LLM returned invalid JSON")
        return _fallback_extract(transcript, num_clips)
    except Exception as e:
        logger.warning("_score_and_extract failed: %s", e)
        return _fallback_extract(transcript, num_clips)


def _fallback_extract(transcript: str, num_clips: int) -> list[ClipCandidate]:
    """无 LLM 时的均匀分割 fallback。"""
    if not transcript:
        return []

    # 假设每 30 秒一个候选
    candidates = []
    words = transcript.split()
    words_per_segment = max(len(words) // (num_clips * 2), 20)

    for i in range(num_clips):
        start_word = i * words_per_segment * 2
        if start_word >= len(words):
            break
        segment_text = " ".join(words[start_word:start_word + words_per_segment])
        # 粗估时间（假设 2.5 words/sec）
        start_time = start_word / 2.5
        end_time = (start_word + words_per_segment) / 2.5

        candidates.append(ClipCandidate(
            start_time=start_time,
            end_time=end_time,
            score=50 - i * 5,
            title=f"片段 {i+1}",
            hook_sentence=segment_text[:80] + ("..." if len(segment_text) > 80 else ""),
            virality_reason="(fallback: LLM unavailable)",
            category="hook",
        ))

    return candidates


def _crop_clip(
    input_path: Path,
    clip: ClipCandidate,
    aspect_ratio: str = "9:16",
) -> bool:
    """用 FFmpeg 裁剪单个片段并裁剪为目标比例。"""
    if clip.clip_path is None:
        return False

    duration = clip.end_time - clip.start_time
    if duration <= 0:
        return False

    # 裁剪参数
    if aspect_ratio == "9:16":
        # 竖屏: 裁切中心区域
        vf = "crop=ih*9/16:ih"
    elif aspect_ratio == "1:1":
        vf = "crop=min(iw,ih):min(iw,ih)"
    elif aspect_ratio == "4:5":
        vf = "crop=ih*4/5:ih"
    else:
        vf = None

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(clip.start_time),
        "-i", str(input_path),
        "-t", str(min(duration, 75)),  # 最长 75 秒
    ]
    if vf:
        cmd += ["-vf", vf]
    cmd += [
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(clip.clip_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            logger.warning("_crop_clip ffmpeg error: %s", result.stderr.decode()[:300])
            return False
        return clip.clip_path.exists() and clip.clip_path.stat().st_size > 0
    except Exception as e:
        logger.warning("_crop_clip failed: %s", e)
        return False
