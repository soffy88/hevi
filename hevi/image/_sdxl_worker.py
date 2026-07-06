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
    ).images[0]

    image.save(task["output_path"])
    print(f"saved {task['output_path']}")


if __name__ == "__main__":
    main()
