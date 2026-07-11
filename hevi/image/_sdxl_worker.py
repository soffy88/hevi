"""SDXL subprocess worker — loads the pipeline, generates one image, exits.

Invoked by sdxl_local_service._run_worker() via subprocess so the ~7GB VRAM
footprint is released the moment generation finishes (same rationale as
Wan2GP's wgp.py subprocess in wan_local_service.py). Never imported directly.

Usage: python _sdxl_worker.py <task.json>
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    task_path = sys.argv[1]
    with open(task_path, encoding="utf-8") as f:
        task = json.load(f)

    import torch
    from diffusers import AutoencoderKL, StableDiffusionXLPipeline

    # CPU 回退(2026-07-08:GPU 掉 PCIe 总线期间验证全链路用,慢但能跑通)——CPU 上
    # fp16 大量算子要么不支持要么极慢,必须切 float32;fp16-variant 权重文件在纯
    # float32 场景下没有对应件,variant 也得跟着置空,否则 from_pretrained 会找不到文件。
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    variant = "fp16" if device == "cuda" else None

    # SDXL's stock fp16 VAE overflows to NaN during decode unless upcast to fp32
    # (diffusers' `upcast_vae` path) — that upcast briefly needs far more VRAM than
    # this GPU has free and OOMs. madebyollin/sdxl-vae-fp16-fix is a re-trained VAE
    # that decodes correctly in fp16 with no upcast, avoiding the OOM entirely.
    # (CPU 路径本来就是 float32,不存在这个 NaN 问题,但复用同一个 VAE 不影响正确性。)
    vae = AutoencoderKL.from_pretrained(
        "madebyollin/sdxl-vae-fp16-fix",
        cache_dir=task.get("cache_dir") or None,
        torch_dtype=dtype,
    )
    pipe = StableDiffusionXLPipeline.from_pretrained(
        task["model_id"],
        vae=vae,
        cache_dir=task.get("cache_dir") or None,
        torch_dtype=dtype,
        variant=variant,
        use_safetensors=True,
    )
    # diffusers 的 tqdm 进度条默认用 \r 原地刷新,不产生真正的 \n——调用方
    # (sdxl_local_service._run_worker)是逐行 `async for line in proc.stdout` 读子
    # 进程输出,读不到 \n 就会一直阻塞在 readline() 上,直到整个生成结束才等到第一个
    # 换行符。CPU 推理一步要几秒(GPU 上一步零点几秒,没这个问题这么明显),真实生成
    # 期间会被误判成"卡住了",被 _SDXL_TIMEOUT_S 硬超时杀掉——关掉进度条,只留
    # print() 的换行输出。
    pipe.set_progress_bar_config(disable=True)

    # 国风水墨 LoRA。constitution 要求"国风水墨插画",而 SDXL Base 1.0 纯 prompt 出不了
    # 真水墨(实测只出扁平数字插画/漫画风,违反 negative_style),必须叠风格 LoRA。fuse
    # 进 UNet/文本编码器权重后 unload,再上 device / load_ip_adapter——顺序很关键:fuse
    # 必须早于 to(device)/enable_model_cpu_offload();先 fuse 再 IP-Adapter 可避免 LoRA
    # 与 IP-Adapter 各自改 attention processor 的冲突。SDXL_LORA_PATH 不设则完全跳过。
    import os

    _lora_path = os.getenv("SDXL_LORA_PATH")
    if _lora_path:
        pipe.load_lora_weights(_lora_path)
        pipe.fuse_lora(lora_scale=float(os.getenv("SDXL_LORA_SCALE", "0.8")))
        pipe.unload_lora_weights()

    extra_kwargs: dict = {}
    ip_adapter_image_path = task.get("ip_adapter_image")
    if ip_adapter_image_path:
        if device != "cuda":
            raise RuntimeError(
                "IP-Adapter conditioning 需要 CUDA(cpu_offload 依赖 GPU 常驻)"
                ",这台机器 GPU 当前不可用"
            )
        # L6 角色一致性:场景底图 + 角色参考图(IP-Adapter)+ 动作 prompt。load_ip_adapter
        # must run before the pipeline is placed on a device.
        from PIL import Image

        pipe.load_ip_adapter(
            "h94/IP-Adapter",
            subfolder="sdxl_models",
            weight_name="ip-adapter_sdxl.bin",
            cache_dir=task.get("cache_dir") or None,
        )
        pipe.set_ip_adapter_scale(float(task.get("ip_adapter_weight", 0.6)))
        extra_kwargs["ip_adapter_image"] = Image.open(ip_adapter_image_path).convert("RGB")

    if ip_adapter_image_path:
        # IP-Adapter's CLIP-ViT-H image encoder (~2.5GB) pushes the base pipeline's
        # 8.6GB peak past this GPU's free VRAM — enable_model_cpu_offload() keeps
        # only the actively-running submodule on GPU instead of the whole pipeline.
        pipe.enable_model_cpu_offload()
        # enable_attention_slicing() after load_ip_adapter() corrupts the IP-Adapter
        # cross-attention processor's encoder_hidden_states (becomes a bare tuple,
        # not the (text, image) pair the processor expects) — skip slicing here;
        # cpu_offload already keeps VRAM in check for the IP-Adapter path.
    else:
        pipe = pipe.to(device)
        if device == "cuda":
            pipe.enable_attention_slicing()
    pipe.vae.enable_tiling()

    generator = torch.Generator(device=device).manual_seed(int(task["seed"]))
    image = pipe(
        prompt=task["prompt"],
        negative_prompt=task.get("negative_prompt") or None,
        width=int(task["width"]),
        height=int(task["height"]),
        num_inference_steps=int(task["num_inference_steps"]),
        guidance_scale=float(task["guidance_scale"]),
        generator=generator,
        **extra_kwargs,
    ).images[0]

    image.save(task["output_path"])
    print(f"saved {task['output_path']}")


if __name__ == "__main__":
    main()
