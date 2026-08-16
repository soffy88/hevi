"""omodul:omodul_lite_assembler —— Lite 管道业务编排层(中枢神经)。

唯一有权调用 oprim 的地方。职责:
  1. 实例化 WorkspaceManager(task_id),管理沙盒目录 + TaskRun 状态机;
  2. 依次执行: TTS 旁白合成(oprim_tts)→ ASR 听声打轴(oprim_asr)
     → HTML 合成(带 data-start/data-end, oprim_html_gen)
     → Playwright 音频驱动录屏(oprim_playwright)
     → FFmpeg 混流(旁白 + 可选 BGM, 强制音频轨校验, oprim_ffmpeg);
  3. Try-Catch 容错:每步标记 state.json(DB),崩溃重试跳过已完成步骤;
  4. 每步同步推进 progress 并推流 WebSocket。

严格 3O:本模块不出现任何业务规则拼装、不直接操作文件系统细节,
所有原子能力都从 hevi.pipeline_lite.oprim 引入。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from hevi.core.workspace import WorkspaceManager
from hevi.pipeline_lite.oprim.oprim_asr import extract_segment_timestamps
from hevi.pipeline_lite.oprim.oprim_broll import fetch_broll_video_url
from hevi.pipeline_lite.oprim.oprim_ffmpeg import (
    assert_audio_track,
    mux_audio_video,
)
from hevi.pipeline_lite.oprim.oprim_html_gen import render_lite_html
from hevi.pipeline_lite.oprim.oprim_playwright import (
    convert_webm_to_mp4,
    record_html_to_video,
)
from hevi.pipeline_lite.oprim.oprim_tts import synthesize_master_audio
from hevi.pipeline_lite.schemas import LiteAssembleResult, LiteTaskContext

logger = logging.getLogger(__name__)


async def run_lite_pipeline(
    task_context: LiteTaskContext,
    *,
    audio_path: str | None = None,
    workspace_root: Any = None,
    tts_synthesize: Any = None,
    allow_silent: bool = False,
    **_kwargs: Any,
) -> LiteAssembleResult:
    """编排一次 Lite 装配: TTS → ASR → HTML → 录屏 → 混流, 全程断点续传。

    ``tts_synthesize`` 注入旁白合成器(缺省 oprim_tts.synthesize_master_audio);
    ``audio_path`` 直接提供音频文件时跳过 TTS; ``allow_silent`` 允许无音轨直出
    (默认 False —— 音频是全链路输入, 失败即失败)。
    """
    ws = WorkspaceManager(
        task_context.task_id,
        pipeline_type="lite_html",
        workspace_root=workspace_root or "data/workspace",
    )
    trail: list[dict[str, Any]] = [
        {"stage": "lite_dispatch", "outcome": "accepted"}
    ]

    try:
        # ── 1. TTS 旁白合成 → master_audio.wav ──────────────
        master_audio: Path | None = None
        if audio_path:
            master_audio = Path(audio_path)
            logger.info("lite %s: 使用外部音频 %s", ws.task_id, master_audio)
        elif not ws.is_step_done("tts"):
            ws.update_progress("tts_processing", 30)
            synth = tts_synthesize or synthesize_master_audio
            try:
                master_audio = Path(
                    await synth(task_context.cues, ws.asset_path("master_audio.wav"))
                )
                if not master_audio.exists() or master_audio.stat().st_size == 0:
                    raise RuntimeError(f"TTS 未产出音频: {master_audio}")
                ws.mark_step_done("tts", progress=40)
                trail.append({"stage": "tts", "outcome": "completed"})
            except Exception as exc:
                if allow_silent:
                    logger.warning("lite %s TTS 失败, 静音直出: %s", ws.task_id, exc)
                    trail.append({"stage": "tts", "outcome": "skipped", "error": str(exc)[:300]})
                    master_audio = None
                else:
                    raise RuntimeError(f"TTS 旁白合成失败: {exc}") from exc
        else:
            existing = ws.asset_path("master_audio.wav")
            master_audio = existing if existing.exists() else None

        # ── 2. ASR 听声打轴 → timestamps.json ────────────────
        timestamps: list[dict[str, Any]] | None = None
        if master_audio is not None and not ws.is_step_done("asr"):
            ws.update_progress("asr_processing", 45)
            timestamps = await extract_segment_timestamps(
                master_audio,
                task_context.cues,
                ws.asset_path("timestamps.json"),
            )
            ws.mark_step_done("asr", progress=50)
            trail.append({"stage": "asr", "outcome": "completed"})
        elif ws.is_step_done("asr"):
            try:
                import json

                timestamps = json.loads(
                    ws.asset_path("timestamps.json").read_text(encoding="utf-8")
                ).get("segments") or None
            except Exception:
                timestamps = None

        # ── 2.5 B-roll 视频背景检索(Pexels, 无 key/失败自动降级) ──
        broll_map: dict[str, str] = {}
        if ws.is_step_done("broll"):
            try:
                import json

                raw: dict[str, Any] = json.loads(
                    ws.asset_path("broll.json").read_text(encoding="utf-8")
                )
                broll_map = {str(k): str(v) for k, v in raw.items()}
            except Exception:
                broll_map = {}
        else:
            ws.update_progress("broll_search", 53)
            for cue in task_context.cues:
                existing_url = str(cue.props.get("broll_url") or "").strip()
                if existing_url:
                    broll_map[str(cue.index)] = existing_url
                    continue
                query = str(cue.props.get("visual_query") or task_context.topic).strip()
                if not query:
                    continue
                try:
                    candidates = await fetch_broll_video_url(query, count=1)
                    if candidates and candidates[0].get("preview_url"):
                        broll_map[str(cue.index)] = str(candidates[0]["preview_url"])
                except Exception as exc:
                    logger.warning("lite %s broll 检索失败(%s), 该卡降级纯色", ws.task_id, exc)
            if broll_map:
                import json

                ws.asset_path("broll.json").write_text(
                    json.dumps(broll_map, ensure_ascii=False), encoding="utf-8"
                )
                trail.append(
                    {"stage": "broll", "outcome": "completed", "cards": len(broll_map)}
                )
            else:
                trail.append({"stage": "broll", "outcome": "skipped", "error": "无 key/无结果"})
            ws.mark_step_done("broll", progress=55)

        # ── 3. HTML 合成(时间戳注入 data-start/data-end) ─────
        if ws.is_step_done("html"):
            logger.info("lite %s: html 已完成,跳过", ws.task_id)
            html_path = ws.asset_path("template.html")
        else:
            ws.update_progress("html_processing", 55)
            html_path = render_lite_html(
                task_context.topic,
                task_context.cues,
                ws.asset_path("template.html"),
                width=task_context.width,
                height=task_context.height,
                timestamps=timestamps,
                broll_map=broll_map,
            )
            ws.mark_step_done("html", progress=60)
            trail.append({"stage": "html_gen", "outcome": "completed"})
        task_context.html_path = html_path

        # ── 4. Playwright 音频驱动录屏 ───────────────────────
        if ws.is_step_done("screen_capture"):
            logger.info("lite %s: 录屏已完成,跳过", ws.task_id)
            capture = ws.asset_path("screen.webm")
        else:
            ws.update_progress("recording", 70)
            duration_s = _expected_duration(timestamps, task_context.cues)
            capture = await record_html_to_video(
                html_path,
                ws.asset_path("screen.webm"),
                width=task_context.width,
                height=task_context.height,
                fps=task_context.fps,
                duration_s=duration_s,
            )
            if not capture.exists() or capture.stat().st_size == 0:
                raise RuntimeError(f"录屏产物为空: {capture}")
            ws.mark_step_done("screen_capture", progress=80)
            trail.append({"stage": "screen_capture", "outcome": "completed"})
        task_context.screen_capture_path = capture

        # ── 5. FFmpeg 混流(旁白 + 可选 BGM) ─────────────────
        if ws.is_step_done("mux"):
            logger.info("lite %s: 混流已完成,跳过", ws.task_id)
            final = ws.output_path(task_context.output_name)
        else:
            ws.update_progress("muxing", 90)
            final = ws.output_path(task_context.output_name)
            if not capture.exists() or capture.stat().st_size == 0:
                raise RuntimeError(f"录屏产物为空,无法混流: {capture}")
            if master_audio is not None and master_audio.exists():
                bgm = os.environ.get("LITE_BGM_PATH")
                final = mux_audio_video(
                    capture,
                    master_audio,
                    final,
                    bgm_path=bgm,
                    remove_original=False,
                )
                assert_audio_track(final)
                trail.append({"stage": "mux", "outcome": "completed"})
            elif capture.suffix.lower() == ".webm":
                # 静音直出: webm → 真 mp4(无音频轨, 跳过音频轨校验)。
                converted = convert_webm_to_mp4(capture, fps=task_context.fps)
                converted.replace(final)
                trail.append({"stage": "mux", "outcome": "completed-silent"})
            else:
                import shutil

                shutil.copy2(capture, final)
                trail.append({"stage": "mux", "outcome": "completed-silent"})
            ws.mark_step_done("mux", progress=100)
        task_context.final_path = final

        # v9.1 产物身份: 成片 SHA-256 绑定, 返工/审核对同一稿。
        ws.record_result_sha(final)

        ws.update_progress("completed", 100)
        return LiteAssembleResult(
            task_id=ws.task_id,
            status="completed",
            video_path=final,
            decision_trail=trail,
            progress=100,
        )
    except Exception as exc:
        logger.exception("lite %s 装配失败", ws.task_id)
        ws.mark_failed(str(exc)[:2000])
        return LiteAssembleResult(
            task_id=ws.task_id,
            status="failed",
            error=f"lite 装配失败: {exc}",
            decision_trail=trail,
            progress=ws.get_state("progress") or 0,
        )


def _expected_duration(
    timestamps: list[dict[str, Any]] | None, cues: list[Any]
) -> float:
    """期望录制时长: 时间戳末段 end, 兜底按 cue 数估算。"""
    if timestamps:
        last = max(float(row.get("end", 0)) for row in timestamps)
        if last > 0:
            return max(last + 2.0, 3.0)
    return max(3.0, len(cues) * 4.0)


__all__ = ["run_lite_pipeline"]
