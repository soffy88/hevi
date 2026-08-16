"""series_animator —— SD 关键帧 + Ken Burns 运镜动画 (本地 GPU)。

一课 → 黄金公式分镜 → SD 1.5 生图关键帧 → ffmpeg Ken Burns 运镜 → TTS → 拼接。
零 API 额度, RTX 3080 10GB 本地运行。
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from hevi.cinematic.golden_formula import GoldenBeat

logger = logging.getLogger(__name__)

VOICE = "zh-CN-XiaoxiaoNeural"
_SD_PIPE = None  # 懒加载, 全局复用


def _get_pipe() -> Any:
    global _SD_PIPE
    if _SD_PIPE is None:
        import torch
        from diffusers import StableDiffusionPipeline
        _SD_PIPE = StableDiffusionPipeline.from_pretrained(  # type: ignore[no-untyped-call]
            "runwayml/stable-diffusion-v1-5", torch_dtype=torch.float16,
            use_safetensors=True, cache_dir="/data/models/huggingface",
        ).to("cuda")
    return _SD_PIPE


def _gen_keyframe(prompt: str, out: Path, *, steps: int = 18) -> Path:
    """SD 1.5 生图关键帧 (768x512, ~3s/张)。"""
    if out.exists() and out.stat().st_size > 1000:
        return out
    img = _get_pipe()(
        prompt, height=512, width=768, num_inference_steps=steps,
        negative_prompt="blurry, low quality, text, watermark",
    ).images[0]
    img.save(str(out))
    return out


def _ken_burns(image: Path, out: Path, duration: float, mov: str = "push_in") -> None:
    """ffmpeg Ken Burns 运镜: 图片 → 带运镜的视频片段。"""
    dur_s = max(3.0, duration)
    if mov == "push_in":
        vf = (
            "scale=8000:-1,zoompan=z='min(zoom+0.001,1.3)':d=1:"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=24"
        )
    elif mov == "pull_out":
        vf = (
            "scale=8000:-1,zoompan=z='if(eq(on,1),1.3,zoom-0.001)':d=1:"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720:fps=24"
        )
    elif mov == "pan":
        vf = "scale=8000:-1,zoompan=z=1.15:x='x+2':y='y+1':d=1:s=1280x720:fps=24"
    elif mov == "tracking":
        vf = "scale=8000:-1,zoompan=z=1.12:x='x+3':y='y+1.5':d=1:s=1280x720:fps=24"
    else:
        vf = "scale=8000:-1,zoompan=z=1.05:x='x+1':y='y+1':d=1:s=1280x720:fps=24"
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(image), "-vf", vf,
         "-t", f"{dur_s:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-an", str(out)],
        capture_output=True, check=True,
    )


def _get_duration(wav: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(wav)], capture_output=True, text=True)
    return float(p.stdout.strip() or 4.0)


async def _tts(text: str, out: Path) -> float:
    """GPU 引擎优先 TTS: Voicebox → CosyVoice → edge-tts 最后兜底。"""
    if out.exists() and out.stat().st_size > 100:
        return _get_duration(out)

    errors: list[str] = []
    # 1. gen-engine Voicebox（生产首选，支持高质量中文音色/指令）
    try:
        from hevi.explainer.voicebox_client import synthesize as voicebox_synthesize
        await voicebox_synthesize(text, out)
        if out.exists() and out.stat().st_size > 100:
            return _get_duration(out)
    except Exception as exc:
        errors.append(f"voicebox: {exc}")

    # 2. gen-engine CosyVoice（GPU 引擎备用）
    try:
        from types import SimpleNamespace

        from hevi.audio.cosyvoice_service import cosyvoice_synthesize
        await cosyvoice_synthesize(
            script=[SimpleNamespace(text=text, speaker_id="narrator")],
            output_path=out,
            watermark=False,
        )
        if out.exists() and out.stat().st_size > 100:
            return _get_duration(out)
    except Exception as exc:
        errors.append(f"cosyvoice: {exc}")

    # 3. 最后兜底 edge-tts（不再作为默认路径）
    try:
        import edge_tts
        await edge_tts.Communicate(text, VOICE).save(str(out))
        if out.exists() and out.stat().st_size > 100:
            return _get_duration(out)
    except Exception as exc:
        errors.append(f"edge-tts: {exc}")
    raise RuntimeError("所有 TTS provider 失败: " + " | ".join(errors))


async def animate_lesson(
    textbook_text: str, *, lesson_title: str = "", llm: Any = None,
    output_dir: Path | None = None,
) -> tuple[Path, list[GoldenBeat]]:
    """一课动画出片: LLM拆解 → SD关键帧 → Ken Burns → TTS → 拼接。"""
    output_dir = Path(output_dir or f"/tmp/series_{lesson_title}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 黄金公式拆解
    if llm is None:
        from hevi.explainer.research import _default_llm
        llm = _default_llm()
    from hevi.cinematic.golden_formula import decompose_story_to_golden_beats

    beats = await decompose_story_to_golden_beats(textbook_text, llm, max_beats=10)
    if not beats:
        for i, sent in enumerate(textbook_text.replace("；", "。").split("。")[:6]):
            s = sent.strip()
            if len(s) > 10:
                beats.append(
                    GoldenBeat(
                        index=i, shot_size="medium", movement="static",
                        subject="", action=s[:60], emotion_expression="",
                        atmosphere="", lighting="", duration_s=4.0,
                        narration=s[:120],
                    )
                )
    if not beats:
        beats = [
            GoldenBeat(
                index=0, shot_size="wide", movement="static",
                subject=lesson_title, action=textbook_text[:80],
                emotion_expression="", atmosphere="", lighting="",
                duration_s=5.0, narration=textbook_text[:120],
            )
        ]

    # 2. 逐镜: TTS 旁白 → SD 关键帧 → Ken Burns 视频
    beat_videos: list[Path] = []
    for i, beat in enumerate(beats):
        beat["index"] = i
        narration = beat.get("narration", "") or beat.get("action", "") or "讲解中"
        nar_wav = output_dir / f"nar_{i:02d}.mp3"
        dur = await _tts(narration, nar_wav)

        # SD 关键帧 prompt: 黄金公式字段拼接
        sd_prompt = f"{beat.get('subject','')} {beat.get('action','')}, "
        sd_prompt += f"{beat.get('emotion_expression','')} {beat.get('atmosphere','')}, "
        sd_prompt += f"{beat.get('lighting','')}, ancient Chinese history, documentary, 4k"
        keyframe = output_dir / f"kf_{i:02d}.png"
        _gen_keyframe(sd_prompt, keyframe)

        # Ken Burns 运镜
        mp4 = output_dir / f"beat_{i:02d}.mp4"
        mov = beat.get("movement", "push_in")
        if not (mp4.exists() and mp4.stat().st_size > 1000):
            _ken_burns(keyframe, mp4, max(dur, 3), mov)
        beat_videos.append(mp4)
        logger.info("beat %d/%d (%.1fs) done", i + 1, len(beats), dur)

    # 3. 拼接视频 + 拼接音频 → mux
    final_video = output_dir / "final_no_audio.mp4"
    _concat_videos(beat_videos, final_video)
    final_audio = output_dir / "audio_final.m4a"
    _concat_audio(output_dir, len(beats), final_audio)
    final = output_dir / "final.mp4"
    _mux(final_video, final_audio, final)
    return final, beats


def _concat_videos(videos: list[Path], output: Path) -> None:
    normed = []
    for i, v in enumerate(videos):
        nv = output.parent / f"norm_{i:02d}.mp4"
        if not nv.exists():
            subprocess.run(["ffmpeg", "-y", "-i", str(v), "-vf", "scale=1280:720,fps=24",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(nv)],
                           capture_output=True, check=True)
        normed.append(nv)
    vlist = output.parent / "vlist.txt"
    vlist.write_text("".join(f"file '{p.resolve()}'\n" for p in normed))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(vlist),
                    "-c:v", "libx264", str(output)], capture_output=True, check=True)


def _concat_audio(output_dir: Path, n: int, output: Path) -> None:
    lines = []
    for i in range(n):
        nar = output_dir / f"nar_{i:02d}.mp3"
        if nar.exists() and nar.stat().st_size > 100:
            lines.append(f"file '{nar.resolve()}'\n")
    if not lines:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                        "-t", "5", str(output)], capture_output=True)
        return
    alist = output_dir / "alist.txt"
    alist.write_text("".join(lines))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alist),
                    "-c:a", "aac", str(output)], capture_output=True, check=True)


def _mux(video: Path, audio: Path, output: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
                    "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                    "-shortest", str(output)], capture_output=True, check=True)
