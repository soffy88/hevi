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

    # SDXL's stock fp16 VAE overflows to NaN during decode unless upcast to fp32
    # (diffusers' `upcast_vae` path) — that upcast briefly needs far more VRAM than
    # this GPU has free and OOMs. madebyollin/sdxl-vae-fp16-fix is a re-trained VAE
    # that decodes correctly in fp16 with no upcast, avoiding the OOM entirely.
    vae = AutoencoderKL.from_pretrained(
        "madebyollin/sdxl-vae-fp16-fix",
        cache_dir=task.get("cache_dir") or None,
        torch_dtype=torch.float16,
    )
    pipe = StableDiffusionXLPipeline.from_pretrained(
        task["model_id"],
        vae=vae,
        cache_dir=task.get("cache_dir") or None,
        torch_dtype=torch.float16,
        variant="fp16",
        use_safetensors=True,
    )

    extra_kwargs: dict = {}
    ip_adapter_image_path = task.get("ip_adapter_image")
    if ip_adapter_image_path:
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
        pipe = pipe.to("cuda")
        pipe.enable_attention_slicing()
    pipe.vae.enable_tiling()

    generator = torch.Generator(device="cuda").manual_seed(int(task["seed"]))
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
