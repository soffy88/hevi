"""v9.1 基建解耦: 全时段数字人 Talking Face —— 轻量 HTTP 客户端。

废弃原来的本地 LongCat 推理(hevi-api 容器内无 GPU、无模型), 改由 GPU 算力
引擎容器(services/ai_engine)承载 LongCat 推理; EchoMimicV2 走本机 ComfyUI:

    1. TALKING_FACE_ENGINE=echomimic → ComfyUI AIFSH EchoMimicV2
       (512² / FP16 / 音频分片, `start-echomimic.sh`, 10G 卡)。
    2. TALKING_FACE_ENGINE=duix → 本机 Duix 容器离线口型(用完停容器,与 Echo 互斥)。
    3. 否则请求 http://hevi-gen-engine:17493/api/ai/longcat (multipart 上传
       播音员照片 + 整条主音频, 引擎返回与音频等长的 MP4)。
    3. 引擎无模型/不可达时直接失败；generic 和 placeholder 只有调用者显式
       选择时才可用于预览，不能作为真实数字人产物的静默降级。

对外 API 不变: generate_talking_face / generate_continuous_avatar_track /
TalkingFaceUnavailable(hevi.digital_human 与 explainer.assembly 依赖)。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TalkingFaceUnavailable(RuntimeError):
    """Talking Face 引擎不可用(引擎未部署/无模型, 或降级路径也失败)。"""


def _engine_base_url() -> str:
    # 生成引擎: GEN_ENGINE_BASE_URL 优先, AI_ENGINE_BASE_URL 兼容回退。
    url = (
        os.environ.get("GEN_ENGINE_BASE_URL")
        or os.environ.get("AI_ENGINE_BASE_URL")
        or "http://hevi-gen-engine:17493"
    )
    return url.rstrip("/")


async def _engine_capabilities() -> dict[str, Any]:
    """查询引擎能力表(GET /api/ai/capabilities), 失败视为引擎不可达。"""
    try:
        async with httpx.AsyncClient(
            base_url=_engine_base_url(),
            timeout=httpx.Timeout(10, connect=5),
        ) as client:
            response = await client.get("/api/ai/capabilities")
            if response.status_code == 200:
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
    except httpx.HTTPError:
        logger.warning("AI 引擎不可达, Talking Face 走本地降级: %s", _engine_base_url())
    return {}


async def _run_duix_offline(
    *,
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    reference_video: Path | None = None,
) -> Path:
    from hevi.digital_human.duix_offline import generate_silent_duix
    from hevi.digital_human.duix_service import DuixUnavailable

    reference = reference_video if reference_video and reference_video.exists() else image_path
    try:
        return await generate_silent_duix(
            reference=reference,
            audio_path=audio_path,
            output_path=output_path,
        )
    except DuixUnavailable as exc:
        raise TalkingFaceUnavailable(f"Duix 离线口型失败: {exc}") from exc


async def _run_echo_mimic(
    *,
    image_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """本机 ComfyUI EchoMimicV2(512² / 分片 / FP16)。"""
    from hevi.providers.echo_mimic.provider import echo_mimic_generate
    from hevi.providers.h3_local.comfy_client import H3ComfyError

    try:
        return await echo_mimic_generate(
            image_path=image_path,
            audio_path=audio_path,
            output_path=output_path,
        )
    except H3ComfyError as exc:
        raise TalkingFaceUnavailable(f"EchoMimicV2 合成失败: {exc}") from exc


async def _run_engine_longcat(
    *,
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    preset_name: str,
    gpu_id: int,
) -> Path:
    """把照片 + 主音频交给引擎的 LongCat 端点, 下载等长 MP4。"""
    timeout = httpx.Timeout(
        float(os.environ.get("AI_ENGINE_TIMEOUT_S", "1800")),
        connect=float(os.environ.get("AI_ENGINE_CONNECT_TIMEOUT_S", "15")),
    )
    try:
        async with httpx.AsyncClient(base_url=_engine_base_url(), timeout=timeout) as client:
            with image_path.open("rb") as img, audio_path.open("rb") as aud:
                response = await client.post(
                    "/api/ai/longcat",
                    files={
                        "image": (image_path.name, img, "image/jpeg"),
                        "audio": (audio_path.name, aud, "audio/wav"),
                    },
                    data={"preset_name": preset_name, "gpu_id": str(gpu_id)},
                )
            if response.status_code == 501:
                raise TalkingFaceUnavailable(
                    f"AI 引擎无 LongCat 模型可用: {_detail(response)}"
                )
            if response.status_code >= 400:
                raise TalkingFaceUnavailable(
                    f"AI 引擎 LongCat 合成失败 (HTTP {response.status_code}): "
                    f"{_detail(response)}"
                )
            if not response.content:
                raise TalkingFaceUnavailable("AI 引擎返回空视频")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
    except TalkingFaceUnavailable:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise TalkingFaceUnavailable(f"AI 引擎服务不可用: {exc}") from exc

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise TalkingFaceUnavailable(f"AI 引擎未产出视频文件: {output_path}")
    return output_path


async def generate_talking_face(
    *,
    image_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    preset_name: str = "default",
    gpu_id: int = 0,
    reference_video: str | Path | None = None,
) -> Path:
    """Generate a full-length talking face video driven by master audio.

    Receives a static presenter photo and a complete master audio track,
    produces a single MP4 that is exactly as long as the audio — to be used
    as the continuous avatar PiP (or fullscreen) track in Remotion.

    Engine selection:
    1. TALKING_FACE_ENGINE=echomimic(默认) → 本机 ComfyUI EchoMimicV2。
       失败直接抛 TalkingFaceUnavailable,不静默占位圈。
    2. TALKING_FACE_ENGINE=duix → 本机 Duix 容器离线口型,用完停容器。
    3. TALKING_FACE_ENGINE=longcat → 强制走引擎 LongCat 端点。
    4. 引擎能力表声明 longcat 可用且未指定 echomimic/duix → 走引擎端点。
    5. generic → 只有显式选择时才使用频谱可视化；placeholder 也必须显式选择。

    生产原则：引擎不可达、模型缺失或未知配置都会失败，不再把占位视频
    当作真实数字人产物交付。
    """
    image_path = Path(image_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    ref_video = Path(reference_video) if reference_video else None

    if not image_path.exists():
        raise TalkingFaceUnavailable(f"Presenter image not found: {image_path}")
    if not audio_path.exists():
        raise TalkingFaceUnavailable(f"Audio file not found: {audio_path}")
    if audio_path.stat().st_size == 0:
        raise TalkingFaceUnavailable(f"Audio file is empty: {audio_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    preset_name = preset_name or "default"

    engine = (os.getenv("TALKING_FACE_ENGINE", "echomimic") or "echomimic").strip().lower()
    capabilities = await _engine_capabilities()
    engine_has_longcat = bool(capabilities.get("longcat"))

    try:
        if engine == "duix":
            result_path = await _run_duix_offline(
                image_path=image_path,
                audio_path=audio_path,
                output_path=output_path,
                reference_video=ref_video,
            )
        elif engine == "echomimic":
            result_path = await _run_echo_mimic(
                image_path=image_path,
                audio_path=audio_path,
                output_path=output_path,
            )
        elif engine == "longcat" or engine_has_longcat:
            result_path = await _run_engine_longcat(
                image_path=image_path,
                audio_path=audio_path,
                output_path=output_path,
                preset_name=preset_name,
                gpu_id=gpu_id,
            )
        elif engine == "generic":
            # 显式选择本地频谱可视化(不是模型口型同步,仅用于预览)。
            result_path = await _run_generic_lipsync(
                image_path=image_path,
                audio_path=audio_path,
                output_path=output_path,
            )
        elif engine == "placeholder":
            # 仅允许显式选择，避免 Provider 故障时静默交付占位视频。
            result_path = await _generate_placeholder_avoiding_null(
                audio_path=audio_path,
                output_path=output_path,
            )
        else:
            raise TalkingFaceUnavailable(
                f"未知 Talking Face 引擎: {engine}; "
                "请选择 echomimic、duix、longcat、generic 或显式 placeholder。"
            )
    except TalkingFaceUnavailable:
        # 真实 Provider 失败必须进入任务失败/重试/人工处理状态。
        raise
    except Exception as exc:
        logger.error("Talking Face generation failed: %s", exc, exc_info=True)
        raise TalkingFaceUnavailable(f"Talking Face 生成失败: {exc}") from exc

    if not result_path.exists() or result_path.stat().st_size == 0:
        raise TalkingFaceUnavailable(f"Talking Face engine produced no output: {result_path}")

    return result_path


async def _run_generic_lipsync(*, image_path: Path, audio_path: Path, output_path: Path) -> Path:
    """Generic lip-sync approach when a specific engine is unavailable.

    Uses ffmpeg to composite the presenter image over a dark background,
    with subtle mouth-area animation derived from audio waveform analysis.
    This is a graceful degradation path.
    """
    # Input: image (still) + audio input, output: talking-face-like video
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-i", str(audio_path),
        "-filter_complex", (
            "[0:v]"
            ",scale=1080:1920,format=yuv420p"
            "[bg];"
            "[1:a]showvolume=f=100:t=0:h=30:w=1080:colors=0x6C63FF[spectrum];"
            "[bg][spectrum]overlay=x=(W-w)/2:y=H-h-40"
        ),
        "-c:v", "libx264",
        "-tune", "animation",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise TalkingFaceUnavailable(
            f"Generic lipsync ffmpeg failed: {stderr.decode(errors='replace')[:500]}"
        )
    return output_path


async def _generate_placeholder_avoiding_null(
    *, audio_path: Path, output_path: Path
) -> Path:
    """Fallback: Generate an animated placeholder so Remotion never has a null track.

    Creates a simple pulsing-circle-with-avatar-silhouette video synced to audio duration.
    This guarantees visual continuity even when no real talking face engine is available.
    """
    from oprim import probe_duration

    duration_s = probe_duration(audio_path)  # type: ignore[no-untyped-call]

    # Use ffmpeg to render a simple animated avatar placeholder
    color_bg = "#0B0F2E"
    skin_color = "#D4A574"
    suit_color = "#4A5ECF"

    drawdesc = (
        f"color={color_bg}:size=1080x1920:duration={duration_s},setpts=PTS-STARTPTS,"
        f"drawcircle=c='white':x=540:y=540:r=80:fc={skin_color},setsar=1,"
        f"drawbox=x=440:y=700:w=200:h=150:b=1:c={suit_color}@0.8,tinterlace=mode=all32,"
        f"scale=1080:1920"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={color_bg}:s=1080x1920:d={duration_s}",
        "-f", "lavfi",
        "-i", "aevalsrc=sin(440*2*3.14159*t)|sin(550*2*3.14159*t):s=48000:channels=2",
        "-filter_complex", drawdesc,
        "-c:v", "libx264",
        "-tune", "animation",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()

    # If the drawtext/avfilter chain failed (older ffmpeg), produce the simplest valid MP4
    if not output_path.exists() or output_path.stat().st_size < 100:
        cmd_simple = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color_bg}:s=1080x1920:d={duration_s}",
            "-f", "lavfi",
            "-i", "aevalsrc=0:s=48000:channels=1",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "32",
            "-c:a", "aac",
            "-t", str(duration_s),
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]
        await asyncio.create_subprocess_exec(
            *cmd_simple,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    return output_path


# ─── Continuous Avatar Track Producer ──────────────────────────────
async def generate_continuous_avatar_track(
    *,
    image_path: str | Path,
    master_audio_path: str | Path,
    output_dir: str | Path,
    aspect_ratio: str = "9:16",
    **kwargs: Any,
) -> Path:
    """v9.0 架构核心: 生成全时段数字人底轨视频。

    一次性生成整条数字人视频, 而非分段拼接。输出直接作为 Remotion 的全局
    底轨播放, 配合 layout_mode 实现 PiP 缩放。
    """
    image_path = Path(image_path)
    master_audio_path = Path(master_audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if aspect_ratio == "9:16":
        out_file = output_dir / "continuous_avatar_p.mp4"
    else:
        out_file = output_dir / "continuous_avatar_l.mp4"

    result = await generate_talking_face(
        image_path=image_path,
        audio_path=master_audio_path,
        output_path=out_file,
        **kwargs,
    )
    logger.info(
        "Continuous avatar track produced: %s (%.1f MB)",
        result, result.stat().st_size / 1_000_000,
    )
    return result


def _detail(response: httpx.Response) -> str:
    import json

    try:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])
    except (ValueError, json.JSONDecodeError):
        pass
    return response.text[:300] or f"HTTP {response.status_code}"
