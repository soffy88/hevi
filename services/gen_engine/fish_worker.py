"""hevi-gen-engine fish-speech 推理 worker —— 独立 ai-venv 子进程入口。

fish-speech 依赖(audiotools 等)与 voicebox 主环境冲突, 装在独立 ai-venv;
本 worker 由 /api/ai/fish_speech 端点以子进程方式调用(与 tts_worker 同模式),
退出即释放显存。

用法:
    /opt/ai-venv/bin/python fish_worker.py <args.json>

Args JSON schema:
    {
      "text": str,
      "model_dir": "/models/fish-speech-1.5",
      "reference_audio": "/path/ref.wav" | null,
      "output_path": "/tmp/speech.wav",
      "max_new_tokens": 512
    }
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-not-found]


def _instantiate_dac(cfg: dict) -> Any:
    """按 yaml _target_ 递归实例化(hydra instantiate 的轻量替代)。"""
    import importlib

    target = cfg.get("_target_")
    if not target:
        raise RuntimeError(f"yaml 缺 _target_: {list(cfg.keys())[:5]}")
    mod_name, _, attr = target.rpartition(".")
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, attr)
    kwargs = {k: v for k, v in cfg.items() if k != "_target_"}
    is_partial = bool(kwargs.pop("_partial_", False))
    # 嵌套组件: 递归实例化含 _target_ 的 dict。
    for key, value in kwargs.items():
        if isinstance(value, dict) and "_target_" in value:
            kwargs[key] = _instantiate_dac(value)
    if is_partial:
        import functools

        return functools.partial(cls, **kwargs)
    return cls(**kwargs)


async def _main(args_path: str) -> None:
    data = json.loads(Path(args_path).read_text(encoding="utf-8"))
    text = data["text"]
    model_dir = Path(data["model_dir"])
    ref_path = Path(data["reference_audio"]) if data.get("reference_audio") else None
    out_path = Path(data["output_path"])
    max_new_tokens = int(data.get("max_new_tokens", 512))

    import torch  # type: ignore[import-not-found]
    from fish_speech.models.text2semantic.inference import (  # type: ignore[import-not-found]
        generate_long,
        init_model,
    )
    from fish_speech.tokenizer import FishTokenizer  # type: ignore[import-not-found]

    # GPU 优先; 显存被 voicebox 等占满时 OOM 降级 CPU(worker 退出即释放)。
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    # VQGAN 解码器(firefly-gan-vq-fsq-8x1024-21hz)。
    def _load():
        import importlib.util

        spec = importlib.util.find_spec("fish_speech")
        locations = spec.submodule_search_locations if spec else None
        if not locations:
            raise RuntimeError("找不到 fish_speech 包位置")
        cfg_path = Path(next(iter(locations))) / "configs" / "firefly_gan_vq.yaml"
        decoder = _instantiate_dac(yaml.safe_load(cfg_path.read_text()))
        state_dict = torch.load(
            str(model_dir / "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"),
            map_location=device, weights_only=True,
        )
        if "state_dict" in state_dict:
            state_dict = state_dict["state_dict"]
        if any("generator" in k for k in state_dict):
            state_dict = {
                k.replace("generator.", ""): v
                for k, v in state_dict.items()
                if "generator." in k
            }
        decoder.load_state_dict(state_dict, strict=False)
        decoder.eval().to(device=device)
        decoder = decoder.float()  # 统一 float32: FSQ 权重可能 bf16, conv bias Half 与输入不匹配
        model, decode_one_token = init_model(str(model_dir), device, dtype)
        tokenizer = FishTokenizer(model_dir / "tokenizer.tiktoken")
        return decoder, model, decode_one_token, tokenizer

    try:
        decoder, model, decode_one_token, _tokenizer = _load()
    except Exception as _exc:
        import gc

        is_oom = (
            "out of memory" in str(_exc).lower()
            or isinstance(_exc, torch.cuda.OutOfMemoryError)  # type: ignore[attr-defined]
        )
        if not is_oom:
            raise
        gc.collect()
        torch.cuda.empty_cache()
        device = "cpu"
        dtype = torch.float32
        decoder, model, decode_one_token, _tokenizer = _load()

    # 参考音色编码(零样本克隆, 可选)。
    prompt_tokens: torch.Tensor | None = None
    if ref_path is not None and ref_path.exists():
        import librosa  # type: ignore[import-not-found]

        waveform, _sr = librosa.load(
            str(ref_path),
            sr=decoder.spec_transform.sample_rate,
            mono=True,
        )
        audio = torch.from_numpy(waveform).unsqueeze(0).unsqueeze(0).to(device)
        audio_lengths = torch.tensor([audio.shape[2]], device=device, dtype=torch.long)
        with torch.no_grad():
            prompt_tokens, _ = decoder.encode(audio, audio_lengths)  # type: ignore[attr-defined]
        if isinstance(prompt_tokens, (tuple, list)):
            prompt_tokens = prompt_tokens[0]

    # 0.1.0 接口: generate_long 接收 text + 参考 tokens; 无参考时传空 tensor
    # (0.1.0 无条件迭代 prompt_tokens, None 会崩)。
    prompt_text = None
    if prompt_tokens is not None:
        prompt_text = text
    else:
        prompt_tokens = torch.empty((0, 0, model.config.num_codebooks), dtype=torch.long)
    with torch.no_grad():
        codes_list = [
            resp.codes
            for resp in generate_long(
                model=model,
                device=device,
                decode_one_token=decode_one_token,
                text=text,
                max_new_tokens=max_new_tokens,
                num_samples=1,
                top_p=0.8,
                repetition_penalty=1.1,
                temperature=0.8,
                prompt_text=prompt_text,
                prompt_tokens=prompt_tokens.cpu() if prompt_tokens is not None else None,
            )
            if resp.codes is not None
        ]
        if not codes_list:
            raise RuntimeError("fish_speech 未生成语义 token")
        # codes: (seq, n_codebooks) → decode 期望 (b, seq, n_codebooks)
        generated = torch.stack(codes_list, dim=0).squeeze(0)
        decoded = decoder.decode(
            indices=generated[None],
            feature_lengths=torch.tensor([generated.shape[1]], device=device),
        )
        waveform = (
            decoded[0].squeeze().cpu().float().numpy()
            if isinstance(decoded, (tuple, list))
            else decoded.squeeze().cpu().float().numpy()
        )

    import soundfile as sf  # type: ignore[import-not-found]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), waveform, decoder.spec_transform.sample_rate)
    print(f"OK {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: fish_worker.py <args.json>", file=sys.stderr)
        sys.exit(1)
    try:
        asyncio.run(_main(sys.argv[1]))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
