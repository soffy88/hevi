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
    from diffusers import AutoencoderKL

    # SPEC-004 v2:init_image 存在 → img2img 分支(从 Subject3D 朝向视图当底图,让朝向真正落到
    # 画面,见 gs1 验证 2026-07-16)。与 IP-Adapter 互斥(img2img 的底图本身就是身份+朝向源,
    # 不叠 IP-Adapter)。否则走原 txt2img 路(含 IP-Adapter 子路)。
    init_image_path = task.get("init_image")
    if init_image_path and task.get("ip_adapter_image"):
        raise RuntimeError("init_image(img2img)与 ip_adapter_image 互斥,不能同时给")
    if init_image_path:
        from diffusers import StableDiffusionXLImg2ImgPipeline as _PipeCls
    else:
        from diffusers import StableDiffusionXLPipeline as _PipeCls

    # ── Gap 1 阶段2:ControlNet-OpenPose 分支(未接,骨架控制图上游已就绪)────────────────
    # 场面调度层已能产出 OpenPose 骨架控制图(scene_render_avatar._compose_pose_control,毫秒级
    # 纯 CPU,多角色镜自动落 {sid}_pose.png)。这里是**唯一缺的消费端**。接它前有三件真机事项,
    # 都无法在本进程里替代,不接则骨架图只是备着、无害:
    #   1) 权重下宿主机(容器 :ro 挂载,联网在容器外下到 settings.sdxl_model_dir):
    #      ~2.5GB `xinsir/controlnet-openpose-sdxl-1.0`(或 ~700MB 的 -small 变体先验证)。
    #   2) 实测 VRAM:CN(~+1.3–2.5GB)叠现有 IP-Adapter 路峰值 7.1GB / 空闲 ~7.4GB,可行性
    #      报告判定"genuinely marginal, real OOM risk",必须真跑量,不能预测。OOM 时退路:
    #      768² 出图 / -small 变体 / enable_sequential_cpu_offload(更慢)。
    #   3) diffusers 0.38 的 StableDiffusionXLControlNetPipeline 同时继承 IPAdapterMixin —— CN
    #      与 IP-Adapter **可共存**(几何 + 锁脸同时要),这正是它比阶段1 img2img 强的地方。接线:
    #        - control_image_path = task.get("control_image")
    #        - _PipeCls = ...ControlNetPipeline / ...ControlNetImg2ImgPipeline(注意 image= vs
    #          control_image= 语义在两个类里相反,弄反不报错只出垃圾)
    #        - controlnet=ControlNetModel.from_pretrained(..., cache_dir=...) 传进 from_pretrained
    #        - offload 分支复用 IP-Adapter 那条(enable_model_cpu_offload,不能 attention slicing)
    #        - 调用 kwargs 加 image=<control map>, controlnet_conditioning_scale=<~0.6>
    #      同样的改动 _sdxl_batch_worker.py 要再做一遍(它硬编码了 txt2img pipeline)。
    #    VRAM 常量 hevi/gpu/providers.py:VRAM_SDXL_LOCAL 接后需重新量。

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
    pipe = _PipeCls.from_pretrained(
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
    elif init_image_path:
        # img2img:同机共享 GPU 另有租户占 ~2.4GiB,cpu_offload 控峰值(gs1 验证过);
        # 无 IP-Adapter,slicing 安全可开。
        pipe.enable_model_cpu_offload()
        if device == "cuda":
            pipe.enable_attention_slicing()
    else:
        pipe = pipe.to(device)
        if device == "cuda":
            pipe.enable_attention_slicing()
    pipe.vae.enable_tiling()

    generator = torch.Generator(device=device).manual_seed(int(task["seed"]))
    call_kwargs: dict = {
        "prompt": task["prompt"],
        "negative_prompt": task.get("negative_prompt") or None,
        "num_inference_steps": int(task["num_inference_steps"]),
        "guidance_scale": float(task["guidance_scale"]),
        "generator": generator,
        **extra_kwargs,
    }
    if init_image_path:
        from PIL import Image

        # img2img 用底图尺寸;把 3D 视图缩到目标尺寸,strength 控保留多少朝向/构图。
        call_kwargs["image"] = (
            Image.open(init_image_path)
            .convert("RGB")
            .resize((int(task["width"]), int(task["height"])))
        )
        call_kwargs["strength"] = float(task.get("strength", 0.5))
    else:
        call_kwargs["width"] = int(task["width"])
        call_kwargs["height"] = int(task["height"])
    image = pipe(**call_kwargs).images[0]

    image.save(task["output_path"])
    print(f"saved {task['output_path']}")


if __name__ == "__main__":
    main()
