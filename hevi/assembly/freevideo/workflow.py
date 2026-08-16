"""freevideo:workflow —— 零成本动画通道编排(3O 三件套签名)。

free_video_workflow(config, input_data, output_dir) →
  {"status": "completed"|"failed", "output_path": ..., "report_path": ...}

流程: 分镜(确定性) → 每镜 HTML → 逐帧录屏 → concat → 报告。
无 LLM、无 TTS、无云视频 API、无素材下载 —— 只耗 CPU。

与 hevi 现有通道的关系:
  - 内容/分镜纪律来自 hevi-story(分句成镜)与 hevi-promo(配方卡/节奏);
  - 渲染路线复刻 html-video(nexu-io/html-video)Hyperframes:自包含动画 HTML
    帧 + headless Chromium 录屏 + ffmpeg 拼接;
  - 录屏原子能力复用 hevi.pipeline_lite.oprim.oprim_playwright(字体冻结/
    动画探测已内化)。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.assembly.freevideo.render import render_frames
from hevi.assembly.freevideo.storyboard import FramePlan, plan_from_json, plan_from_text

logger = logging.getLogger(__name__)


@dataclass
class FreeVideoConfig:
    """渲染配置(确定性参数)。"""

    width: int = 1280
    height: int = 720
    fps: int = 30
    frame_duration: float = 4.0  # 每镜时长(秒),录屏后精确裁剪
    palette: str = "deep"  # deep | paper
    frame_kind: str | None = None  # 指定单一模板(全部镜);None = 自动轮换
    # 免费程序化 BGM(hevi.audio.procedural_bgm):mood 给定时自动合成并混入成片
    bgm_mood: str | None = None  # calm | bright | epic | tense | warm
    bgm_bpm: int = 0  # 0 = 用 mood 预设
    bgm_duration_s: float = 0.0  # 0 = 自动(等于成片时长,向上取整到小节)
    bgm_volume: float = 1.0  # 直接混入(无旁白)时保持合成器内置低音量
    # 免费配音:voice 给定时合成旁白并混入(BGM 自动 duck 到旁白下)。
    # voice 支持:edge_tts 音色键(CURATED_VOICES)/ "fish"(本地 fish-speech 默认音色)/
    # "fish:/path/ref.wav"(本地 fish-speech 零样本声音克隆)。
    voice: str | None = None
    narration: str = ""  # 旁白文本;为空时自动拼接各帧 body


@dataclass
class FreeVideoInput:
    """输入:文本 或 结构化分镜 JSON(二选一)。"""

    text: str = ""  # 中文文本 → 确定性分句成镜
    title: str = ""
    plans: list[FramePlan] | None = None  # 显式分镜(优先)
    plans_json: str | None = None  # 或 JSON 字符串
    extra: dict[str, Any] = field(default_factory=dict)


def build_plans(
    config: FreeVideoConfig, input_data: FreeVideoInput
) -> list[FramePlan]:
    """输入 → FramePlan 列表(确定性,不调模型)。"""
    if input_data.plans:
        return input_data.plans
    if input_data.plans_json:
        return plan_from_json(input_data.plans_json)
    if input_data.text.strip():
        return plan_from_text(
            input_data.text,
            title=input_data.title,
            frame_duration=config.frame_duration,
            kind=config.frame_kind,
        )
    raise ValueError("FreeVideoInput 需要 text 或 plans/plans_json 之一")


async def free_video_workflow(
    config: FreeVideoConfig,
    input_data: FreeVideoInput,
    output_dir: Path,
    *,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """标准 omodul:分镜 → 逐帧渲染 → concat → 报告。失败不 raise。"""
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_trail: list[dict[str, Any]] = []

    def _step(stage: str, pct: float) -> None:
        if callable(on_step):
            on_step({"stage": stage, "pct": pct})

    try:
        plans = build_plans(config, input_data)
        _step("storyboard", 8.0)
        decision_trail.extend(
            {"stage": "frame", "kind": p.kind, "title": p.title[:30]} for p in plans
        )

        output_path = output_dir / "freevideo.mp4"
        await render_frames(
            plans,
            output_path,
            width=config.width,
            height=config.height,
            fps=config.fps,
            palette=config.palette,
            on_step=lambda stage, pct: _step(stage, pct),
        )
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"成片为空: {output_path}")

        # 免费程序化 BGM + 免费配音(edge_tts):合成后混音。
        # 注意:mux_audio_video 的 amix duration=first 会把成片裁到旁白长度,
        # 且 -shortest+copy 时容器时长异常 —— 这里自己拼 ffmpeg:amix
        # duration=longest 让 BGM 铺满视频(旁白播完续 BGM),视频流拷贝。
        bgm_info: dict[str, Any] | None = None
        voice_info: dict[str, Any] | None = None
        if config.bgm_mood or config.voice:
            from hevi.assembly.freevideo.render import _ffmpeg
            from hevi.audio.procedural_bgm import BgmConfig, generate_bgm_file
            from hevi.pipeline_lite.oprim.oprim_ffmpeg import assert_audio_track

            bgm_wav: Path | None = None
            if config.bgm_mood:
                est_dur = sum(p.duration for p in plans)
                bgm_cfg = BgmConfig(
                    mood=config.bgm_mood,
                    bpm=config.bgm_bpm,
                    duration_s=config.bgm_duration_s or est_dur,
                    gain=0.32,
                )
                bgm_wav, grid = generate_bgm_file(bgm_cfg, output_dir / "bgm.wav")
                (output_dir / "bgm_beats.json").write_text(
                    json.dumps(grid.to_dict(), ensure_ascii=False), encoding="utf-8"
                )
                bgm_info = {
                    "mood": config.bgm_mood,
                    "bpm": grid.bpm,
                    "beats": grid.beat_count,
                    "beats_path": str(output_dir / "bgm_beats.json"),
                }
                _step("bgm", 97.0)

            narr_wav: Path | None = None
            if config.voice:
                narration = config.narration or "。".join(
                    p.body for p in plans if p.body
                )
                if config.voice.startswith("fish"):
                    # 本地 fish-speech(Dual-AR,零样本声音克隆):fish / fish:/path/ref.wav
                    from hevi.audio.fish_speech_local import fish_speech_local_synthesize

                    ref = config.voice.split(":", 1)[1] if ":" in config.voice else None
                    narr_wav = output_dir / "narration.wav"
                    try:
                        await fish_speech_local_synthesize(
                            narration, narr_wav, reference_audio=ref
                        )
                    except Exception as _fse:
                        logger.warning(
                            "fish-speech 本地合成失败(%s),退回 edge_tts", _fse
                        )
                        narr_wav = None
                if narr_wav is None:
                    from hevi.audio.edge_tts_custom import CURATED_VOICES

                    voice_name = CURATED_VOICES.get(config.voice, config.voice)
                    narr_wav = output_dir / "narration.wav"
                    await _synthesize_narration(narration, voice_name, narr_wav)
                voice_info = {"voice": config.voice, "chars": len(narration)}
                _step("tts", 98.5)

            if narr_wav is not None or bgm_wav is not None:
                muxed = output_dir / "freevideo_bgm.mp4"
                inputs: list[str] = ["-i", str(output_path)]
                if narr_wav is not None:
                    inputs += ["-i", str(narr_wav)]
                if bgm_wav is not None:
                    inputs += ["-i", str(bgm_wav)]
                filters: list[str] = []
                next_idx = 1
                if narr_wav is not None:
                    filters.append(f"[{next_idx}:a]anull[a_voice]")
                    voice_label = "[a_voice]"
                    next_idx += 1
                if bgm_wav is not None:
                    vol = 0.15 if narr_wav is not None else config.bgm_volume
                    filters.append(f"[{next_idx}:a]volume={vol}[a_bgm]")
                    bgm_label = "[a_bgm]"
                    next_idx += 1
                if narr_wav is not None and bgm_wav is not None:
                    filters.append(
                        "[a_voice][a_bgm]amix=inputs=2:duration=longest:dropout_transition=2[a_out]"
                    )
                else:
                    labels = voice_label if narr_wav is not None else bgm_label
                    filters.append(f"{labels}anull[a_out]")
                _ffmpeg(
                    [
                        *inputs,
                        "-filter_complex", ";".join(filters),
                        "-map", "0:v", "-map", "[a_out]",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart",
                        str(muxed),
                    ]
                )
                assert_audio_track(muxed)
                muxed.replace(output_path)
        _step("done", 100.0)

        report = {
            "status": "completed",
            "output_path": str(output_path),
            "frames": len(plans),
            "resolution": f"{config.width}x{config.height}@{config.fps}fps",
            "est_duration_s": round(len(plans) * config.frame_duration, 1),
            "zero_cost": True,
            "bgm": bgm_info,
            "voice": voice_info,
            "decision_trail": decision_trail,
            "plan": [p.to_dict() for p in plans],
        }
        report_path = output_dir / "freevideo_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"status": "completed", "output_path": str(output_path), "report_path": str(report_path), **report}
    except Exception as exc:
        logger.exception("free_video_workflow failed")
        return {
            "status": "failed",
            "error": str(exc),
            "report_path": str(output_dir / "freevideo_report.json"),
        }


async def _synthesize_narration(text: str, voice: str, out_path: Path) -> Path:
    """edge_tts 单段旁白 → WAV(免费,微软神经语音;hevi 已有该依赖)。

    失败抛 RuntimeError,由 workflow 捕获转 failed(不 raise)。
    """
    import edge_tts

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(out_path))
    except Exception as exc:  # pragma: no cover - 网络/服务异常
        raise RuntimeError(f"edge_tts 旁白合成失败: {exc}") from exc
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"edge_tts 未产出音频: {out_path}")
    return out_path


__all__ = ["FreeVideoConfig", "FreeVideoInput", "free_video_workflow"]
