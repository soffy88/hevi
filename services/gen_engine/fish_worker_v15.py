"""fish-speech v1.5 本地推理 worker —— Dual-AR 架构官方推理链的独立子进程入口。

与 fish_worker.py(v1.4 接口)并存:本 worker 用 fish-speech v1.5.0 官方
`TTSInferenceEngine`(tools/ 包),兼容 fish-speech-1.5 权重(`model_type: dual_ar`)。
v1.4 的 init_model/generate_long 加载 dual_ar 权重能出 token 但解码静音 ——
这是 1.5 权重必须走本 worker 的原因。

用法(与 fish_worker.py 相同的 args JSON 契约):
    <python> fish_worker_v15.py <args.json>
Args JSON:
    {
      "text": str,
      "model_dir": "/home/soffy/models/fish-speech-1.5",
      "reference_audio": "/path/ref.wav" | null,   # 零样本声音克隆(可选)
      "output_path": "/tmp/speech.wav",
      "max_new_tokens": 1024
    }
子进程退出即释放显存;GPU 显存不足时 OOM 降级 CPU。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))
    text = data["text"]
    model_dir = Path(data["model_dir"])
    ref_path = Path(data["reference_audio"]) if data.get("reference_audio") else None
    out_path = Path(data["output_path"])
    max_new_tokens = int(data.get("max_new_tokens", 1024))

    import torch
    import torchaudio

    # torchaudio ≥2.7 移除了 list_audio_backends;ReferenceLoader.__init__ 仍调用。
    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    precision = torch.float16 if device == "cuda" else torch.bfloat16

    from tools.inference_engine import TTSInferenceEngine
    from tools.llama.generate import launch_thread_safe_queue
    from tools.schema import ServeReferenceAudio, ServeTTSRequest
    from tools.vqgan.inference import load_model as load_decoder_model

    llama_queue = launch_thread_safe_queue(
        checkpoint_path=str(model_dir),
        device=device,
        precision=precision,
        compile=False,
    )
    decoder = load_decoder_model(
        config_name="firefly_gan_vq",
        checkpoint_path=str(model_dir / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"),
        device=device,
    )
    engine = TTSInferenceEngine(
        llama_queue=llama_queue,
        decoder_model=decoder,
        precision=precision,
        compile=False,
    )

    references: list[ServeReferenceAudio] = []
    if ref_path is not None and ref_path.exists():
        references = [ServeReferenceAudio(audio=ref_path.read_bytes(), text="")]

    req = ServeTTSRequest(
        text=text,
        references=references,
        max_new_tokens=max_new_tokens,
        streaming=False,
    )

    import numpy as np
    import soundfile as sf

    segments: list[np.ndarray] = []
    sample_rate = 44100
    for result in engine.inference(req):
        if result.code == "error":
            raise RuntimeError(f"fish-speech v1.5 推理错误: {result.error}")
        if result.code == "segment" and isinstance(result.audio, tuple):
            sample_rate = int(result.audio[0])
            segments.append(result.audio[1])
        if result.code == "final" and isinstance(result.audio, tuple):
            sample_rate = int(result.audio[0])
            segments.append(result.audio[1])

    if not segments:
        raise RuntimeError("fish-speech v1.5 未生成音频")

    waveform = np.concatenate(segments) if len(segments) > 1 else segments[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), waveform, sample_rate, subtype="PCM_16")
    print(f"OK {out_path} ({len(waveform) / sample_rate:.1f}s @{sample_rate}Hz)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <args.json>")
    _main(sys.argv[1])
