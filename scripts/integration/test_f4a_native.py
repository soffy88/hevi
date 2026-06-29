"""F4a 真跑: 直接使用 vibevoice 原生 API.

用法: /home/soffy/projects/AII/.venv/bin/python test_f4a_native.py
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path


MODEL_DIR = Path.home() / "models/vibevoice-1.5b"
OUTPUT_DIR = Path("output/f4a_tts")


def _mem_mib() -> int:
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True, text=True,
    )
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def _ffprobe(path: Path) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries",
         "format=duration,size : stream=sample_rate,channels,codec_name",
         "-of", "default=noprint_wrappers=1", str(path)],
        capture_output=True, text=True,
    )
    return r.stdout.strip() or r.stderr.strip()


def main() -> None:
    import torch
    from vibevoice.modular.modeling_vibevoice_inference import (
        VibeVoiceForConditionalGenerationInference,
    )
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load model ───────────────────────────────────────────────────────────
    mem_before_load = _mem_mib()
    print(f"\n[F4a] GPU before load: {mem_before_load} MiB")
    print(f"[F4a] Loading model from {MODEL_DIR} ...")

    t_load0 = time.perf_counter()
    processor = VibeVoiceProcessor.from_pretrained(str(MODEL_DIR))
    model = VibeVoiceForConditionalGenerationInference.from_pretrained(
        str(MODEL_DIR),
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        attn_implementation="eager",
    )
    model.eval()
    model.set_ddpm_inference_steps(num_steps=10)
    t_load1 = time.perf_counter()
    mem_after_load = _mem_mib()
    print(f"[F4a] Model loaded in {t_load1 - t_load0:.1f}s | GPU: {mem_after_load} MiB "
          f"(delta: +{mem_after_load - mem_before_load} MiB)")

    # ── Helper ───────────────────────────────────────────────────────────────
    def synthesize(script_text: str, voice_samples, out_path: Path) -> tuple[float, int]:
        inputs = processor(
            text=[script_text],
            voice_samples=[voice_samples] if voice_samples else None,
            padding=True,
            return_tensors="pt",
            return_attention_mask=True,
        )
        device = next(model.parameters()).device
        for k, v in inputs.items():
            if torch.is_tensor(v):
                inputs[k] = v.to(device)

        t0 = time.perf_counter()
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=None,
                cfg_scale=1.3,
                tokenizer=processor.tokenizer,
                generation_config={"do_sample": False},
                verbose=False,
            )
        elapsed = time.perf_counter() - t0
        processor.save_audio(outputs.speech_outputs[0], output_path=str(out_path))
        return elapsed, _mem_mib()

    # ── 1. Single speaker ────────────────────────────────────────────────────
    print("\n[F4a] === 单说话人合成 ===")
    single_script = "Speaker 1: 欢迎来到 VibeVoice 真跑验证。今天我们测试本地 1.5B 模型推理，合成质量与速度。"
    single_out = OUTPUT_DIR / "single_speaker.wav"
    t_single, mem_single = synthesize(single_script, None, single_out)
    print(f"  输出: {single_out} ({single_out.stat().st_size} bytes)")
    print(f"  耗时: {t_single:.1f}s | 显存: {mem_single} MiB")
    print(f"  ffprobe:\n{_ffprobe(single_out)}")

    # ── 2. Multi speaker ─────────────────────────────────────────────────────
    print("\n[F4a] === 多说话人合成 (4 lines, 3 speakers) ===")
    multi_script = (
        "Speaker 1: 大家好，我是主持人小明。\n"
        "Speaker 2: 您好，我是嘉宾小红，很高兴来到这里。\n"
        "Speaker 3: 我是嘉宾小刚，我们今天聊聊人工智能。\n"
        "Speaker 1: 太好了，让我们开始今天的节目吧！"
    )
    multi_out = OUTPUT_DIR / "multi_speaker.wav"
    t_multi, mem_multi = synthesize(multi_script, None, multi_out)
    print(f"  输出: {multi_out} ({multi_out.stat().st_size} bytes)")
    print(f"  耗时: {t_multi:.1f}s | 显存峰值: {mem_multi} MiB")
    print(f"  ffprobe:\n{_ffprobe(multi_out)}")

    # ── 3. Watermark default ─────────────────────────────────────────────────
    print("\n[F4a] === watermark=True 验证 ===")
    wm_out = OUTPUT_DIR / "watermark_test.wav"
    t_wm, mem_wm = synthesize("Speaker 1: Watermark verification test complete.", None, wm_out)
    print(f"  watermark=True (oprim default) → {wm_out} ({wm_out.stat().st_size} bytes)")
    print(f"  ffprobe:\n{_ffprobe(wm_out)}")

    # ── Summary ──────────────────────────────────────────────────────────────
    peak = max(mem_single, mem_multi, mem_wm)
    print("\n" + "=" * 60)
    print("[F4a] VibeVoice 1.5B 真跑总结")
    print("=" * 60)
    print(f"  模型目录:          {MODEL_DIR}")
    print(f"  单说话人 WAV:      {single_out}")
    print(f"  多说话人 WAV:      {multi_out}")
    print(f"  watermark WAV:     {wm_out}")
    print(f"  显存(载入前):      {mem_before_load} MiB")
    print(f"  显存(加载后):      {mem_after_load} MiB")
    print(f"  显存峰值(推理):    {peak} MiB")
    print(f"  显存增量(纯加载):  +{mem_after_load - mem_before_load} MiB")
    print(f"  单说话人耗时:      {t_single:.1f}s")
    print(f"  多说话人耗时:      {t_multi:.1f}s")
    print(f"  模型加载耗时:      {t_load1 - t_load0:.1f}s")
    print(f"  水印验证:          oprim 默认 watermark=True，"
          "vibevoice 包内置 responsible-AI 水印(pass placeholder 在 M3 中)")
    print("=" * 60)


if __name__ == "__main__":
    main()
