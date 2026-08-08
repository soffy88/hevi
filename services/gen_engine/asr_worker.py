"""hevi-gen-engine VibeVoice-ASR 推理 worker —— VibeASR.cpp(CPU 边缘引擎)。

用微软 VibeASR.cpp(ggml, Qwen2.5-1.5B BitNet 量化, 1.58GB)做 CPU 实时识别,
无需 GPU。worker 子进程调用 asr_infer 二进制, 输出纯文本(单 utterance)。

用法:
    python asr_worker.py <args.json>

Args JSON schema:
    {
      "audio_path": "/tmp/input.wav",
      "vae_model": "/models/vibeasr/vibeasr-vae-encoder-i8_s.gguf",
      "lm_model": "/models/vibeasr/vibeasr-lm-i2_s-embed-q6_k.gguf",
      "hotwords": ["智伯", "晋阳"],
      "output_json": "/tmp/out.json"
    }
输出: {"utterances": [{"speaker","start","end","text"}]}
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))
    audio_path = Path(data["audio_path"])
    vae_model = data["vae_model"]
    lm_model = data["lm_model"]
    hotwords = list(data.get("hotwords") or [])
    out_path = Path(data["output_json"])

    cmd = [
        "/opt/vibeasr/asr_infer",
        "--vae-model", vae_model,
        "--lm-model", lm_model,
        "--audio", str(audio_path),
        "-t", str(data.get("threads", 4)),
        "--greedy",
    ]
    if hotwords:
        cmd += ["--context", "、".join(hotwords)]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-600:] or (proc.stdout or "")[-600:]
        raise RuntimeError(f"asr_infer exit={proc.returncode}: {tail}")

    text = _extract_text(proc.stdout)
    utterances = (
        [{"speaker": "", "start": "0.0", "end": "0.0", "text": text}]
        if text.strip()
        else []
    )
    out_path.write_text(
        json.dumps(
            {"utterances": utterances},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"OK {len(utterances)} utterances")


def _extract_text(stdout: str) -> str:
    """从 asr_infer stdout 提取识别文本(取最后一个非空、非状态行)。"""
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    skip_prefixes = ("INFO", "ggml", "main:", "[", "=", "-", "VAE", "LM", "Audio", "RTF", "Total")
    for line in reversed(lines):
        if line.startswith(skip_prefixes):
            continue
        return line
    return ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: asr_worker.py <args.json>", file=sys.stderr)
        sys.exit(1)
    try:
        _main(sys.argv[1])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
