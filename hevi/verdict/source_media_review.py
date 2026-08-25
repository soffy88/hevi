"""源片审查 —— 用户提供素材的标准化检查, 产出 source_media_review 工件。

对标 OpenMontage lib/source_media_review.py(3O 内化, 差距 B1 补面):
管线反复发明各自的局部检查(只看时长 / 只看有无音频), 本模块统一
为「真实探测 + 质量风险 + 可用性推断 + 规划影响」四段式工件。

契约: 只要用户提供了素材, source_media_review 必须在首个依赖创作假设
的规划阶段之前跑完。**绝不**声称某文件已审查, 除非真跑过探测。

依赖适配(相对 OpenMontage 的 tool_registry):
  - 视频/音频探测 → ffprobe(subprocess, 与 delivery_gate 同款调用)
  - 代表帧 → hevi/verdict/frame_extract.py(PyAV, 不依赖系统 ffmpeg 二进制)
  - 转写 → 可选注入 callable(缺省跳过, 不阻塞审查)
全部失败降级为 quality_risks 条目, 不抛异常。
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from hevi.verdict.frame_extract import FrameExtractError, extract_representative_frame

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"})
_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".opus"})
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".svg"})

_FFPROBE_TIMEOUT_S = 30


def detect_media_type(path: Path) -> str | None:
    """按扩展名归类 video / audio / image, 不认识返回 None。"""
    ext = path.suffix.lower()
    if ext in _VIDEO_EXTENSIONS:
        return "video"
    if ext in _AUDIO_EXTENSIONS:
        return "audio"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    return None


def _ffprobe_json(path: Path) -> dict[str, Any] | None:
    """ffprobe 整文件 JSON(-show_format -show_streams)。失败返回 None。"""
    if not shutil.which("ffprobe"):
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=_FFPROBE_TIMEOUT_S,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            parsed = json.loads(result.stdout)
            return cast(dict[str, Any], parsed) if isinstance(parsed, dict) else None
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
    return None


def _parse_fps(fps_str: str) -> float:
    """解析 ffprobe fps 串 '30/1' / '24000/1001'。"""
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            return round(int(num) / max(int(den), 1), 2)
        return float(fps_str)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _sample_timestamps(duration: float, count: int = 4) -> list[float]:
    """均匀散布采样时间戳(避开首尾黑场)。"""
    if duration <= 0:
        return [0.0]
    if count <= 1:
        return [duration / 2]
    step = duration / (count + 1)
    return [round(step * (i + 1), 2) for i in range(count)]


def _probe_video(path: Path, transcribe: Callable[[Path], str] | None = None) -> dict[str, Any]:
    """视频: ffprobe 技术探测 + 代表帧 + 质量风险。"""
    result: dict[str, Any] = {"technical_probe": {}, "representative_frames": [], "quality_risks": []}

    raw = _ffprobe_json(path)
    if raw:
        fmt = raw.get("format", {})
        streams = raw.get("streams", [])
        v: dict[str, Any] = next(
            (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"),
            {},
        )
        a: dict[str, Any] = next(
            (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"),
            {},
        )
        result["technical_probe"] = {
            "duration_seconds": float(fmt.get("duration", 0) or 0),
            "resolution": f"{v.get('width', '?')}x{v.get('height', '?')}",
            "fps": _parse_fps(str(v.get("r_frame_rate", "0/1"))),
            "codec": v.get("codec_name", "unknown"),
            "audio_codec": a.get("codec_name", ""),
            "sample_rate": int(a.get("sample_rate", 0) or 0),
            "channels": int(a.get("channels", 0) or 0),
            "file_size_bytes": int(fmt.get("size", 0) or 0),
            "bitrate_kbps": round(int(fmt.get("bit_rate", 0) or 0) / 1000, 1),
        }
    else:
        result["quality_risks"].append("ffprobe 不可用或探测失败 —— 技术参数未知")

    probe = result["technical_probe"]
    if probe:
        res = str(probe.get("resolution", ""))
        if "x" in res:
            try:
                w, h = res.split("x")
                if w.isdigit() and h.isdigit() and (int(w) < 720 or int(h) < 480):
                    result["quality_risks"].append(f"分辨率偏低 ({res}), 成片可能发糊")
            except ValueError:
                pass
        if probe.get("channels") == 1:
            result["quality_risks"].append("单声道 —— 若目标为立体声需评估")
        if probe.get("duration_seconds", 0) < 3:
            result["quality_risks"].append("时长过短(<3s), 可用性受限")

    # 代表帧(帧抽取失败不阻塞审查)
    try:
        duration = probe.get("duration_seconds", 0) if probe else 0
        timestamps = _sample_timestamps(float(duration))
        out_dir = path.parent / ".source_review_frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        for _i, ts in enumerate(timestamps):
            out_path = out_dir / f"{path.stem}_t{ts:.2f}.png"
            try:
                extract_representative_frame(path, out_path)
                result["representative_frames"].append(str(out_path))
            except FrameExtractError as exc:
                logger.warning("frame sample %s failed: %s", ts, exc)
                break
    except Exception as exc:  # pragma: no cover - 环境兜底
        logger.warning("frame sampling failed for %s: %s", path, exc)

    # 可选转写摘要
    if transcribe is not None:
        try:
            text = transcribe(path)
            if text and text.strip():
                words = text.split()
                if len(words) > 100:
                    result["transcript_summary"] = f"{' '.join(words[:100])}... ({len(words)} words total)"
                else:
                    result["transcript_summary"] = text.strip()
        except Exception as exc:
            logger.warning("transcription failed for %s: %s", path, exc)

    return result


def _probe_audio(path: Path) -> dict[str, Any]:
    """音频: ffprobe 技术探测 + 质量风险。"""
    result: dict[str, Any] = {"technical_probe": {}, "quality_risks": []}
    raw = _ffprobe_json(path)
    if raw:
        fmt = raw.get("format", {})
        a: dict[str, Any] = next(
            (
                s
                for s in raw.get("streams", [])
                if isinstance(s, dict) and s.get("codec_type") == "audio"
            ),
            {},
        )
        result["technical_probe"] = {
            "duration_seconds": float(fmt.get("duration", 0) or 0),
            "audio_codec": a.get("codec_name", "unknown"),
            "sample_rate": int(a.get("sample_rate", 0) or 0),
            "channels": int(a.get("channels", 0) or 0),
            "file_size_bytes": int(fmt.get("size", 0) or 0),
            "bitrate_kbps": round(int(fmt.get("bit_rate", 0) or 0) / 1000, 1),
        }
    else:
        result["quality_risks"].append("ffprobe 不可用或探测失败 —— 音频参数未知")
    return result


def _probe_image(path: Path) -> dict[str, Any]:
    """图片: PIL 元数据探测(无 PIL 退化为文件大小)。"""
    result: dict[str, Any] = {"technical_probe": {}, "quality_risks": []}
    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
        result["technical_probe"] = {
            "resolution": f"{w}x{h}",
            "file_size_bytes": path.stat().st_size,
            "codec": img.format or "unknown",
        }
        if w < 640 or h < 480:
            result["quality_risks"].append(f"分辨率偏低 ({w}x{h}), 可能需要放大")
    except ImportError:  # pragma: no cover - env guard
        result["technical_probe"] = {"file_size_bytes": path.stat().st_size}
    except Exception as exc:
        result["quality_risks"].append(f"图片探测失败: {exc}")
    return result


def _infer_video_usability(probe: dict[str, Any], transcript: str | None) -> list[str]:
    """推断视频文件的可用途径。"""
    uses: list[str] = []
    dur = probe.get("duration_seconds", 0)
    if dur > 10:
        uses.append("hero footage")
    if dur > 3:
        uses.append("b-roll")
    if transcript:
        uses.append("source dialogue")
    if probe.get("audio_codec"):
        uses.append("source audio")
    return uses or ["short clip"]


def _infer_audio_usability(probe: dict[str, Any], transcript: str | None) -> list[str]:
    """推断音频文件的可用途径。"""
    uses: list[str] = []
    dur = probe.get("duration_seconds", 0)
    if transcript:
        uses.append("narration source")
    if dur > 30:
        uses.append("background music candidate")
    if dur > 5:
        uses.append("sound effect or ambient")
    return uses or ["audio clip"]


def review_source_media(
    files: list[Path | str],
    context: dict[str, Any] | None = None,
    transcribe: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    """审查用户素材, 产出 source_media_review 工件。

    Args:
        files: 待审查文件路径。
        context: 可选上下文(预留 pipeline_type / project_dir 等)。
        transcribe: 可选转写 callable(path -> 文本), 缺省跳过转写。

    Returns:
        Schema 化工件: {version, files[], summary, planning_implications[]}。
        单个文件探测失败只记 quality_risks, 不中断整批。
    """
    reviewed: list[dict[str, Any]] = []
    implications: list[str] = []
    summaries: list[str] = []

    for raw in files:
        file_path = Path(raw)
        media_type = detect_media_type(file_path)
        if media_type is None:
            logger.warning("跳过不认识的类型: %s", file_path)
            continue
        if not file_path.exists():
            logger.warning("文件不存在: %s", file_path)
            continue

        entry: dict[str, Any] = {
            "path": str(file_path),
            "media_type": media_type,
            "reviewed": True,
        }

        if media_type == "video":
            probe_data = _probe_video(file_path, transcribe)
        elif media_type == "audio":
            probe_data = _probe_audio(file_path)
        else:
            probe_data = _probe_image(file_path)

        entry["technical_probe"] = probe_data.get("technical_probe", {})
        entry["quality_risks"] = probe_data.get("quality_risks", [])
        entry["representative_frames"] = probe_data.get("representative_frames", [])
        if probe_data.get("transcript_summary"):
            entry["transcript_summary"] = probe_data["transcript_summary"]

        probe = entry["technical_probe"]
        transcript = entry.get("transcript_summary")
        if media_type == "video":
            dur = probe.get("duration_seconds", 0)
            res = probe.get("resolution", "unknown")
            has_audio = bool(probe.get("audio_codec"))
            entry["content_summary"] = (
                f"Video file: {dur:.1f}s at {res}, "
                f"{'with' if has_audio else 'without'} audio"
            )
            entry["usable_for"] = _infer_video_usability(probe, transcript)
        elif media_type == "audio":
            dur = probe.get("duration_seconds", 0)
            entry["content_summary"] = (
                f"Audio file: {dur:.1f}s, {probe.get('audio_codec', 'unknown')}"
            )
            entry["usable_for"] = _infer_audio_usability(probe, transcript)
        else:
            entry["content_summary"] = f"Image file: {probe.get('resolution', 'unknown')}"
            entry["usable_for"] = ["visual asset", "reference image"]

        summaries.append(f"{file_path.name}: {entry['content_summary']}")
        reviewed.append(entry)
        implications.extend(
            f"Quality risk in {file_path.name}: {risk}"
            for risk in entry.get("quality_risks", [])
        )

    if not reviewed:
        summary = "No user-supplied media files could be reviewed."
        implications.append("No source media available — production is fully generated.")
    else:
        summary = "; ".join(summaries)

    has_video = any(f["media_type"] == "video" for f in reviewed)
    has_audio = any(f["media_type"] == "audio" for f in reviewed)
    has_images = any(f["media_type"] == "image" for f in reviewed)

    if has_video:
        implications.append("Source video available — consider source-led or hybrid production approach")
    if has_audio and not has_video:
        implications.append("Audio-only source — production needs visual assets to accompany audio")
    if has_images and not has_video:
        implications.append("Image-only source — motion must come from animation or video generation")

    if not implications:
        implications.append("No specific constraints identified from source media.")

    return {
        "version": "1.0",
        "files": reviewed,
        "summary": summary,
        "planning_implications": implications,
    }


def has_user_media(project_dir: Path | str) -> bool:
    """项目目录是否含用户素材(任一视频/音频/图片扩展名)。"""
    root = Path(project_dir)
    if not root.exists():
        return False
    for ext_set in (_VIDEO_EXTENSIONS, _AUDIO_EXTENSIONS, _IMAGE_EXTENSIONS):
        for ext in ext_set:
            if list(root.glob(f"*{ext}")):
                return True
    return False


__all__ = [
    "detect_media_type",
    "has_user_media",
    "review_source_media",
]
