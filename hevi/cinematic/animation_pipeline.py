"""animation_pipeline —— 动画演绎任务编排 (黄金公式出片流水线)。

把 golden_formula(拆解) + edge-tts(解说) + 文生视频(wan2.7-t2v) +
ffmpeg(拼接) 串成可独立调度的编排函数, 供 HTTP 路由在后台任务里调用;
进度通过 progress_cb(percent, stage, shot_index) 上报 → ws 推送 + TaskRun。

完整故事交代: 拆解出的分镜矩阵含 narration(旁白) + 黄金公式字段, 每镜
视频时长对齐旁白, 尾部寓意镜头自然收尾。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.cinematic.golden_formula import (
    GoldenBeat,
    decompose_story_to_golden_beats,
)

logger = logging.getLogger(__name__)

VOICE = "zh-CN-XiaoxiaoNeural"

_EDGE_TTS_SNIPPET = """
import asyncio, sys
import edge_tts

async def _main() -> None:
    text, out = sys.argv[1], sys.argv[2]
    voice = sys.argv[3] if len(sys.argv) > 3 else "zh-CN-XiaoxiaoNeural"
    await edge_tts.Communicate(text, voice).save(out)

asyncio.run(_main())
"""
MODEL = "wan_2_7"               # wan2.7-t2v (阿里云 Model Studio 已开通)
RESOLUTION = "720P"
MIN_SHOT_S = 3
MAX_SHOT_S = 15

ProgressCb = Callable[[int, str, int], None]   # (percent, stage, shot_index)


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{r.stderr[-800:]}")


def _wav_duration(wav: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(wav)],
        capture_output=True, text=True,
    )
    return float(p.stdout.strip() or 0.0)


async def _tts(beat: GoldenBeat, wav: Path) -> float:
    """GPU 引擎优先旁白: Voicebox → CosyVoice → edge-tts 最后兜底。"""
    if wav.exists() and wav.stat().st_size > 0:
        return _wav_duration(wav)

    errors: list[str] = []
    # 1. gen-engine Voicebox（生产高质量中文音色）
    try:
        from hevi.explainer.voicebox_client import synthesize as voicebox_synthesize

        await voicebox_synthesize(beat.narration, wav)
        if wav.exists() and wav.stat().st_size > 0:
            return _wav_duration(wav)
    except Exception as exc:
        errors.append(f"voicebox: {exc}")

    # 2. gen-engine CosyVoice
    try:
        from types import SimpleNamespace

        from hevi.audio.cosyvoice_service import cosyvoice_synthesize

        await cosyvoice_synthesize(
            script=[SimpleNamespace(text=beat.narration, speaker_id="narrator")],
            output_path=wav,
            watermark=False,
        )
        if wav.exists() and wav.stat().st_size > 0:
            return _wav_duration(wav)
    except Exception as exc:
        errors.append(f"cosyvoice: {exc}")

    # 3. edge-tts 最后兜底，保留重试但不再是默认 provider
    for attempt in range(3):
        try:
            _run([sys.executable, "-c", _EDGE_TTS_SNIPPET,
                  beat.narration, str(wav)])
            if wav.exists() and wav.stat().st_size > 0:
                return _wav_duration(wav)
        except Exception as exc:
            errors.append(f"edge-tts[{attempt + 1}]: {exc}")
        await asyncio.sleep(1.5)
    raise RuntimeError("所有 TTS provider 失败: " + " | ".join(errors)[-1000:])


async def _gen_shot(
    beat: GoldenBeat, duration_s: int, out: Path, ratio: str,
    html_dir: Path | None = None, narration_audio: Path | None = None,
) -> str:
    """降级链: 阿里云 wan_2_7 → WaveSpeed → 本机 HTML/CSS 动画 (零额度)。

    任何 provider 失败都不开天窗 (同 C6 降级链哲学); 返回实际渲染路径
    ("wan"/"wavespeed"/"html")。
    """
    from hevi.cinematic.animation_html import render_html_shot
    from hevi.video.alibaba_maas_service import AlibabaMaasError, alibaba_maas_generate
    from hevi.video.wavespeed_service import wavespeed_generate

    # 1) 阿里云 wan_2_7 (免费额度)
    try:
        await alibaba_maas_generate(
            prompt=beat.shot_prompt, output_path=out, model=MODEL,
            ratio=ratio, resolution=RESOLUTION, duration=duration_s,
            seed=20260711 + beat.index,
        )
        return "wan"
    except (AlibabaMaasError, Exception) as exc:
        logger.warning("阿里 wan_2_7 失败(%s), 降级 WaveSpeed", exc)
    # 2) WaveSpeed wan_2_7
    try:
        await wavespeed_generate(
            prompt=beat.shot_prompt, output_path=out, model=MODEL,
            aspect_ratio=ratio, resolution="720p", duration_s=duration_s,
            seed=20260711 + beat.index,
        )
        return "wavespeed"
    except Exception as exc:
        logger.warning("WaveSpeed 失败(%s), 降级本机 HTML 动画", exc)
    # 3) 本机 HTML/CSS 动画 (零 API 额度, 永不开天窗)
    if html_dir is None or narration_audio is None:
        raise RuntimeError("动画 provider 全失败且无 HTML 降级输入")
    w, h = (1280, 720) if ratio == "16:9" else (720, 1280)
    await render_html_shot(beat, html_dir, out, narration_audio=narration_audio,
                           width=w, height=h)
    return "html"


async def run_animation_pipeline(
    story: str,
    *,
    task_id: str,
    output_dir: Path,
    llm: Any = None,
    beats: list[GoldenBeat] | None = None,
    progress_cb: ProgressCb | None = None,
    ratio: str = "16:9",
) -> tuple[Path, list[dict[str, Any]], dict[str, list[str]]]:
    """完整出片: 拆解 → 解说 → 逐镜动画 → 拼接 → (视频路径, 分镜表)。

    beats 缺省走 LLM 拆解 (失败回退内置模板逻辑——本函数不内置故事模板,
    由路由层提供 fallback beats)。progress_cb 同步调用, 在事件循环里安全。
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _cb = progress_cb or (lambda *_: None)

    # 1. 黄金公式拆解
    _cb(5, "拆解分镜", -1)
    if beats is None:
        beats = await decompose_story_to_golden_beats(story, llm) if llm else []
        if not beats:
            raise RuntimeError("黄金公式拆解失败: LLM 未返回有效分镜")
    n = len(beats)
    if not beats:
        raise RuntimeError("分镜为空")
    renderers: list[str] = []

    # 2. 逐镜: 旁白 → 量长 → 动画视频 (时长对齐旁白)
    durs: list[float] = []
    for i, beat in enumerate(beats):
        _cb(10 + int(80 * i / n), f"解说+演绎 镜{i + 1}/{n}", i)
        nar = output_dir / f"nar_{i:02d}.mp3"
        durs.append(await _tts(beat, nar))
        shot_dur = max(MIN_SHOT_S, min(MAX_SHOT_S, round(max(
            beat.duration_s, durs[-1] + 0.8))))
        shot = output_dir / f"beat_{i:02d}.mp4"
        renderer = "cached"
        if not (shot.exists() and shot.stat().st_size > 100_000):
            renderer = await _gen_shot(
                beat, shot_dur, shot, ratio,
                html_dir=output_dir / "html", narration_audio=nar,
            )
        renderers.append(renderer)
        logger.info("animation %s shot %d done (%.1fs via %s)",
                    task_id, i, durs[-1], renderer)

    # 3. 拼接
    _cb(92, "拼接合成", -1)
    final = _concat(output_dir, n)
    _cb(100, "完成", -1)
    return final, [b.to_dict() for b in beats], {"renderers": renderers}


def _concat(output_dir: Path, n: int) -> Path:
    """统一分辨率/fps → concat → mux 旁白 → 最终视频。"""
    norm = output_dir / "norm"
    norm.mkdir(exist_ok=True)
    normed: list[Path] = []
    for i in range(n):
        v = output_dir / f"beat_{i:02d}.mp4"
        nv = norm / f"v{i:02d}.mp4"
        if not nv.exists():
            _run(["ffmpeg", "-y", "-i", str(v), "-vf", "scale=1280:720,fps=24",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(nv)])
        normed.append(nv)
    vlist = output_dir / "vlist.txt"
    vlist.write_text("".join(f"file '{p.resolve()}'\n" for p in normed))
    video = output_dir / "video_concat.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(vlist),
          "-c", "copy", str(video)])
    alist = output_dir / "alist.txt"
    alist.write_text("".join(
        f"file '{(output_dir / f'nar_{i:02d}.mp3').resolve()}'\n"
        for i in range(n)
    ))
    audio = output_dir / "audio_concat.m4a"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alist),
          "-af", "apad=pad_dur=2", "-c:a", "aac", str(audio)])
    final = output_dir / "final.mp4"
    _run(["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
          "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
          "-shortest", str(final)])
    return final


__all__ = ["ProgressCb", "run_animation_pipeline"]
