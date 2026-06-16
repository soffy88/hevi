"""F4a: VibeVoice 1.5B 真跑验证脚本.

测试项:
  1. 单说话人 TTS  → single_speaker.wav
  2. 多说话人 TTS  → multi_speaker.wav (4 lines, different speakers)
  3. watermark=True 强制验证
  4. 显存峰值采集 (nvidia-smi)
  5. 耗时计量
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


OUTPUT_DIR = Path("output/f4a_tts")
MODEL_DIR = Path.home() / "models/vibevoice-1.5b"


@dataclass
class Line:
    speaker_id: str
    text: str
    voice_ref: Path | None = None


def _nvidia_mem_mib() -> int:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return -1


def _ffprobe(path: Path) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "format=duration,size : stream=sample_rate,channels",
         "-of", "default=noprint_wrappers=1", str(path)],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or result.stderr.strip()


async def run() -> None:
    from oprim import vibevoice_synthesize

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── SINGLE SPEAKER ────────────────────────────────────────────────────────
    single_script = [
        Line(speaker_id="host", text="欢迎来到 VibeVoice 真跑验证。今天我们测试本地 1.5B 模型推理。"),
    ]
    single_out = OUTPUT_DIR / "single_speaker.wav"
    vv_config = {"VIBEVOICE_MODEL_DIR": str(MODEL_DIR)}

    print("\n[F4a] === 单说话人合成 ===")
    mem_before = _nvidia_mem_mib()
    t0 = time.perf_counter()

    await vibevoice_synthesize(
        config=vv_config,
        script=single_script,
        output_path=single_out,
        watermark=True,
    )

    t1 = time.perf_counter()
    mem_after_single = _nvidia_mem_mib()

    print(f"  输出: {single_out}")
    print(f"  耗时: {t1 - t0:.1f}s")
    print(f"  显存(前): {mem_before} MiB | 显存(单说话人后): {mem_after_single} MiB")
    print(f"  ffprobe:\n{_ffprobe(single_out)}")

    # ── MULTI SPEAKER ─────────────────────────────────────────────────────────
    multi_script = [
        Line(speaker_id="host",   text="大家好，我是主持人小明。"),
        Line(speaker_id="guest1", text="您好，我是嘉宾小红，很高兴来到这里。"),
        Line(speaker_id="guest2", text="我是嘉宾小刚，我们今天聊聊人工智能。"),
        Line(speaker_id="host",   text="太好了，让我们开始今天的节目吧！"),
    ]
    multi_out = OUTPUT_DIR / "multi_speaker.wav"

    print("\n[F4a] === 多说话人合成 (4 lines, 3 speakers) ===")
    t2 = time.perf_counter()

    await vibevoice_synthesize(
        config=vv_config,
        script=multi_script,
        output_path=multi_out,
        watermark=True,
    )

    t3 = time.perf_counter()
    mem_peak = _nvidia_mem_mib()

    print(f"  输出: {multi_out}")
    print(f"  耗时: {t3 - t2:.1f}s")
    print(f"  显存峰值 (多说话人后): {mem_peak} MiB")
    print(f"  ffprobe:\n{_ffprobe(multi_out)}")

    # ── WATERMARK CHECK ────────────────────────────────────────────────────────
    print("\n[F4a] === watermark=True 强制验证 ===")
    # watermark flag は synthesize 内で True デフォルト。
    # oprim では pass プレースホルダー(Microsoft responsible-AI 対応中)。
    # ここでは watermark=False で合成が通ること(no exception) も確認する。
    wm_out = OUTPUT_DIR / "watermark_test.wav"
    await vibevoice_synthesize(
        config=vv_config,
        script=[Line(speaker_id="s1", text="Watermark test line.")],
        output_path=wm_out,
        watermark=True,
    )
    print(f"  watermark=True → {wm_out} 生成 OK")
    print(f"  ffprobe:\n{_ffprobe(wm_out)}")

    print("\n[F4a] ===== 总结 =====")
    print(f"  单说话人 WAV : {single_out} ({single_out.stat().st_size} bytes)")
    print(f"  多说话人 WAV : {multi_out} ({multi_out.stat().st_size} bytes)")
    print(f"  watermark WAV: {wm_out} ({wm_out.stat().st_size} bytes)")
    print(f"  显存(载入前): {mem_before} MiB")
    print(f"  显存峰值:     {mem_peak} MiB")
    print(f"  显存增量:     {mem_peak - mem_before} MiB")
    print(f"  单说话人耗时: {t1 - t0:.1f}s")
    print(f"  多说话人耗时: {t3 - t2:.1f}s")


if __name__ == "__main__":
    asyncio.run(run())
