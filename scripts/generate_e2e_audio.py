"""Synthesize spoken speech using local CosyVoice-300M-SFT and generate SRT."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Add CosyVoice to sys.path
cosy_dir = Path("/data/soffy/cosyvoice/CosyVoice")
sys.path.extend([str(cosy_dir), str(cosy_dir / "third_party" / "Matcha-TTS")])

import torch
import torchaudio

torch.set_num_threads(4)

from cosyvoice.cli.cosyvoice import CosyVoice

SCRIPT_LINES = [
    # Line 1: Title
    "很多人都在谈复利，但为什么复利最难的是前三年？",
    # Line 2: Versus
    "很多人以为前三年收益微薄毫无用处，其实前三年是底层基数的积累期。",
    # Line 3: Number
    "在最初的三年里，账户增长极其缓慢，超过百分之七十的人都在这个阶段放弃。",
    # Line 4: Transition (rejected segment)
    "我们来看一组真实数据对比：假设本金100万，年化收益率百分之十。",
    # Line 5: Compare
    "第一年收益只有10万，而到了第十年单年收益就能达到26万。",
    # Line 6: Steps
    "这就是复利的三个完整阶段：第一阶段是积累期，第二阶段是临界期，第三阶段才是爆发期。",
    # Line 7: Network
    "前三年之所以痛苦，是因为它属于典型的单点连接，还没有形成密集的资产网络。",
    # Line 8: Focus
    "面对漫长的平台期，摆在投资者面前有多种选择，但真正有效的只有持续留在场内。",
    # Line 9: Shot
    "这是公开市场三十年历史统计凭证，每一次周期底部都印证着基数效应。",
    # Line 10: Quote
    "最后请记住这句话：复利最难的不是数学，而是熬过前三年的毫无感觉。",
]


def format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> None:
    out_dir = Path("/data/soffy/projects/hevi-riso/output/riso_e2e")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading CosyVoice-300M-SFT model...")
    model_path = "/data/soffy/cosyvoice/models/CosyVoice-300M-SFT"
    cosy = CosyVoice(model_path)
    sr = cosy.sample_rate

    audio_segments = []
    srt_blocks = []
    current_time = 0.5  # 0.5s initial breath

    # Add 0.5s silence at start
    silence_start = torch.zeros(1, int(sr * 0.5))
    audio_segments.append(silence_start)

    print(f"Synthesizing {len(SCRIPT_LINES)} lines with CosyVoice ('中文男')...")
    for idx, line in enumerate(SCRIPT_LINES):
        t0 = time.time()
        gen = cosy.inference_sft(line, "中文男", stream=False)
        line_wav = torch.cat([g["tts_speech"] for g in gen], 1)
        dur = line_wav.shape[1] / float(sr)
        gen_time = time.time() - t0

        start_ts = current_time
        end_ts = current_time + dur

        audio_segments.append(line_wav)

        # 0.6s gap between sentences
        gap_wav = torch.zeros(1, int(sr * 0.6))
        audio_segments.append(gap_wav)

        srt_blocks.append(
            f"{idx + 1}\n{format_srt_time(start_ts)} --> {format_srt_time(end_ts)}\n{line}\n"
        )
        print(f"[{idx+1}/{len(SCRIPT_LINES)}] {dur:.1f}s audio in {gen_time:.1f}s: {line[:24]}...")

        current_time = end_ts + 0.6

    # Concatenate all
    full_audio = torch.cat(audio_segments, 1)
    total_duration = full_audio.shape[1] / float(sr)
    out_wav = out_dir / "speech_cosyvoice.wav"
    torchaudio.save(str(out_wav), full_audio, sr)

    out_srt = out_dir / "speech.srt"
    out_srt.write_text("\n".join(srt_blocks), encoding="utf-8")

    print(f"Synthesized full speech: {total_duration:.2f}s (~{total_duration/60:.1f} min)")
    print(f"Audio written: {out_wav}")
    print(f"SRT written: {out_srt}")


if __name__ == "__main__":
    main()
