"""SDXL batch subprocess worker — loads the pipeline once, generates many images, exits.

Used by sdxl_local_service.sdxl_local_generate_batch() for call sites that need
several images back-to-back from the same identity/style (HEVI-EXEC-01 M2
identity-pack construction: ~17 SDXL calls per character) without paying a full
model reload + CUDA init/teardown per image. That per-image subprocess churn
(one full GPU power-cycle every few seconds) was implicated in a GPU-fallen-off-
PCIe-bus fault (Xid 79) under this load pattern on this host's consumer-grade
hardware — see hevi/image/sdxl_local_service.py:sdxl_local_generate_batch.

Assumes all items in a batch share ip_adapter usage (identity-pack builds never
use it); mixed ip_adapter/non-ip_adapter batches degrade to cpu-offload mode for
every item if any item requests it.

Usage: python _sdxl_batch_worker.py <task.json>
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

    # CPU 回退(2026-07-08:GPU 掉 PCIe 总线期间验证全链路用,慢但能跑通)——见
    # _sdxl_worker.py 同样的改动理由(CPU 上 fp16 大量算子不支持/极慢,须用 float32,
    # variant 也得跟着置空)。
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    variant = "fp16" if device == "cuda" else None

    # Same NaN-at-decode workaround as _sdxl_worker.py — see that file's comment.
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
    # 同 _sdxl_worker.py 的理由:关掉 tqdm 进度条(默认 \r 刷新不产生 \n,调用方逐行
    # 读 stdout 容易被拖慢的输出节奏拖成"看起来卡住了"),批量场景步数更多,累积影响
    # 更明显。
    pipe.set_progress_bar_config(disable=True)

    # 国风水墨 LoRA(同 _sdxl_worker.py 的理由与顺序约束):fuse 进权重后 unload,须早于
    # to(device)/cpu_offload 与 load_ip_adapter。身份包批量重建就靠这条把画风从 SDXL
    # Base 的漫画感拉到真水墨。SDXL_LORA_PATH 不设则跳过。
    import os

    _lora_path = os.getenv("SDXL_LORA_PATH")
    if _lora_path:
        pipe.load_lora_weights(_lora_path)
        pipe.fuse_lora(lora_scale=float(os.getenv("SDXL_LORA_SCALE", "0.8")))
        pipe.unload_lora_weights()

    items = task["items"]
    uses_ip_adapter = any(item.get("ip_adapter_image") for item in items)
    if uses_ip_adapter:
        if device != "cuda":
            raise RuntimeError(
                "IP-Adapter conditioning 需要 CUDA(cpu_offload 依赖 GPU 常驻)"
                ",这台机器 GPU 当前不可用"
            )
        pipe.load_ip_adapter(
            "h94/IP-Adapter",
            subfolder="sdxl_models",
            weight_name="ip-adapter_sdxl.bin",
            cache_dir=task.get("cache_dir") or None,
        )
        pipe.enable_model_cpu_offload()
    else:
        pipe = pipe.to(device)
        if device == "cuda":
            pipe.enable_attention_slicing()
    pipe.vae.enable_tiling()

    results: list[dict[str, object]] = []

    def _flush_results() -> None:
        # Rewritten after every item (not just once at the end) so a mid-batch CUDA
        # crash — which kills this whole process, not just the current pipe() call —
        # still leaves the caller a partial results.json for the items completed so
        # far, instead of losing the entire batch's progress to one bad crash.
        with open(task["results_path"], "w", encoding="utf-8") as f:
            json.dump(results, f)

    for item in items:
        try:
            extra_kwargs: dict = {}
            if item.get("ip_adapter_image"):
                from PIL import Image

                pipe.set_ip_adapter_scale(float(item.get("ip_adapter_weight", 0.6)))
                extra_kwargs["ip_adapter_image"] = Image.open(item["ip_adapter_image"]).convert(
                    "RGB"
                )

            generator = torch.Generator(device=device).manual_seed(int(item["seed"]))
            image = pipe(
                prompt=item["prompt"],
                negative_prompt=item.get("negative_prompt") or None,
                width=int(item["width"]),
                height=int(item["height"]),
                num_inference_steps=int(item["num_inference_steps"]),
                guidance_scale=float(item["guidance_scale"]),
                generator=generator,
                **extra_kwargs,
            ).images[0]
            image.save(item["output_path"])
            print(f"saved {item['output_path']}")
            results.append({"ok": True})
        except Exception as e:  # noqa: BLE001 — isolate one item's failure from the rest of the batch
            print(f"failed {item['output_path']}: {e}", file=sys.stderr)
            results.append({"ok": False, "error": str(e)})
        finally:
            _flush_results()


if __name__ == "__main__":
    main()
