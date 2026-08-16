"""后处理工序编排 —— raw.mp4 → final.mp4(FlashVSR 超分 → RIFE 插帧 → 回混 H3 原音)。

hevi 纪律(与镜头状态机一致):
  - 先超分、后插帧(顺序不可反;反了 RIFE 处理更多帧,显存与耗时显著上升)。
  - 只处理画面;音频始终用 H3 raw 原轨回混(对白轨优先 H3 原生音,不无故 TTS 覆盖)。
  - 每道工序失败 → **降级交付**上一步产物 + 在 .post.json 记录(可跳过,标记 no_interp),
    绝不把 raw 卡死在后处理上。
  - 统一 fps:插帧 2× → 48(24×2);未插帧 → 24。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from obase.ffmpeg import run as ffmpeg_run

from hevi.post.flashvsr import upscale_flashvsr
from hevi.post.rife_vs import RifeUnavailable, has_audio, interpolate_rife

logger = logging.getLogger(__name__)

#: 环境/配置键与默认值(与 .env.example 对齐)。
_UPSCALE_MODES = ("off", "flashvsr")
_INTERP_MODES = ("off", "rife2x", "flowframes")


@dataclass
class PostResult:
    """一道后处理工序的账本(写 .post.json 侧车文件,供装配/verdict 消费)。"""

    final_path: Path
    upscaled: bool = False
    interpolated: bool = False
    fps_out: int = 24
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_path": str(self.final_path),
            "upscaled": self.upscaled,
            "interpolated": self.interpolated,
            "fps_out": self.fps_out,
            "notes": self.notes,
        }


async def _mux_audio(video: Path, audio_src: Path, out: Path) -> Path:
    """把 audio_src 的音轨合到 video(画面不动,音频用 raw 原轨)。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    await ffmpeg_run(
        args=[
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio_src),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(out),
        ],
        timeout_s=300.0,
        expected_output=out,
    )
    return out


async def run_post_pipeline(
    raw_path: Path | str,
    output_path: Path | str,
    *,
    config: dict[str, Any] | None = None,
    fps_in: int = 24,
    comfy_client: Any = None,
) -> PostResult:
    """raw → (FlashVSR 2×) → (RIFE 2×) → final,音频回混 raw 原轨。

    config 键(缺省读环境变量,与 .env.example 对齐):
        upscale:   off | flashvsr      (POST_UPSCALE)
        interp:    off | rife2x | flowframes  (POST_INTERP)
        rife:      rife_kwargs / engine / flowframes_exe (POST_RIFE_*)
        flashvsr:  workflow / comfy_url (POST_FLASHVSR_WORKFLOW / H3_COMFY_URL)
        fps_in:    原片帧率(默认 24)
    """
    cfg = dict(config or {})
    raw, final = Path(raw_path), Path(output_path)
    if not raw.exists():
        raise FileNotFoundError(f"post pipeline 输入不存在: {raw}")

    upscale_mode = str(cfg.get("upscale") or os.getenv("POST_UPSCALE", "flashvsr")).lower()
    interp_mode = str(cfg.get("interp") or os.getenv("POST_INTERP", "rife2x")).lower()
    if upscale_mode not in _UPSCALE_MODES:
        raise ValueError(f"POST_UPSCALE 只能是 {'/'.join(_UPSCALE_MODES)}, 拿到 {upscale_mode!r}")
    if interp_mode not in _INTERP_MODES:
        raise ValueError(f"POST_INTERP 只能是 {'/'.join(_INTERP_MODES)}, 拿到 {interp_mode!r}")

    final.parent.mkdir(parents=True, exist_ok=True)
    result = PostResult(final_path=final, fps_out=fps_in)
    stem = final.stem
    # 中间产物侧车:xxx.raw.mp4 / xxx.up.mp4 —— 供 verdict 与人工复查(断点续跑可复用)。
    up_path = final.with_name(f"{stem}.up.mp4")

    # ── ① 超分(可降级:失败 → 用 raw 继续) ────────────────────────────────
    current = raw
    if upscale_mode == "flashvsr":
        try:
            vsr_cfg = dict(cfg.get("flashvsr") or {})
            vsr_cfg.setdefault("comfy_url", cfg.get("comfy_url"))
            await upscale_flashvsr(
                raw, up_path, config=vsr_cfg or None, client=comfy_client, fps=fps_in
            )
            current = up_path
            result.upscaled = True
            logger.info("post[%s]: FlashVSR 2× 完成 → %s", stem, up_path.name)
        except Exception as e:
            result.notes.append(f"upscale_skipped:{type(e).__name__}")
            logger.warning("post[%s]: 超分不可用,降级交付 raw: %s", stem, e)

    # ── ② 插帧(可跳过:失败 → 用上一步产物,标记 no_interp) ─────────────────
    if interp_mode in ("rife2x", "flowframes"):
        rife_cfg = dict(cfg.get("rife") or {})
        if interp_mode == "flowframes":
            rife_cfg["engine"] = "flowframes"
        try:
            await interpolate_rife(
                current, final, config=rife_cfg or None, multiplier=2, timeout_s=900.0
            )
            result.interpolated = True
            result.fps_out = fps_in * 2
            logger.info("post[%s]: RIFE 2× 完成 → %s", stem, final.name)
        except RifeUnavailable as e:
            result.notes.append("no_interp")
            logger.warning("post[%s]: 插帧不可用,标记 no_interp 降级: %s", stem, e)
            shutil.copy2(current, final)
    else:
        shutil.copy2(current, final)

    # ── ③ 音频回混:对白轨优先 H3 原音,不无故 TTS 覆盖 ─────────────────────
    if raw != final and await has_audio(raw):
        try:
            muxed = final.with_name(f"{stem}.mux.mp4")
            await _mux_audio(final, raw, muxed)
            muxed.replace(final)
        except Exception as e:
            result.notes.append(f"audio_mux_skipped:{type(e).__name__}")
            logger.warning("post[%s]: 音频回混失败,保留纯画面版本: %s", stem, e)

    # ── ④ 账本 .post.json(装配器/verdict 消费:fps、no_interp 标记) ─────────
    try:
        final.with_suffix(final.suffix + ".post.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("post[%s]: 写 .post.json 失败: %s", stem, e)
    return result
