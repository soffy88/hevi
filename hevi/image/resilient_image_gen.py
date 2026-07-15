"""本地 SDXL 不可用时的兜底 image_gen —— 见 memory: RTX 3080 反复 Xid 79 掉出 PCIe
总线,且掉线时机不可预测(跟负载模式无关,更像纯硬件故障),没法靠"预检一次就放心
跑完整批"来规避。这里改成每张图独立探活+可降级,一张图撞见卡挂了不连累其余图。

三级降级:本地 GPU → 本地 CPU(免费但慢,降分辨率/步数换时间)→ 云端 fal.ai Flux
(真花钱)。CPU 排在云端前面是故意的:2026-07-09 实测过 CPU 回退在换成英文视觉
prompt(见 hevi/vault/identity_pack.py 的 image_appearance/image_era_lock)后能稳定
出可用的人物内容,没理由 GPU 一挂就先烧云端账户的钱——CPU 免费只是慢。

云端兜底只用 fal.ai Flux(见 _cloud_fallback),不用 json2video:2026-07-08 实测把
json2video/flux-schnell 接进来生成人物肖像(EXEC-01 M2 身份包 3 个角色),技术上调用
全部成功(HTTP 200、文件正常落盘),但内容系统性文不对题——9 张多视角图全是建筑/
夜景/河景照,没有一张人物,还夹了一张带 hallucinated 水印文字的图。VLM/CLIP 一致性
检查正确识别出这些不是人物肖像(3 个角色稳定性预检全部 0/3),没有被误 promote,但
$3.06 的调用全打了水漂。json2video_scene_service.py 模块 docstring 本就写明"只能
用于无角色场景底图,没有 IP-Adapter 类一致性机制"——当初把它也接进人物类兜底链,是
错误类比了这条限制的性质(以为只是"缺乏跨图一致性",实际是它对含人物描述的中文
prompt 处理本身就很差)。json2video_scene_generate 仍然是 L6 无角色场景底图
(generate_scene_assets)的合法云端备选,只是不该出现在这条人物身份包兜底链里。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from hevi.cost.circuit_breaker import CostLimit, CostTracker
from hevi.image.sdxl_local_service import (
    GPUUnavailableError,
    check_gpu_available,
    sdxl_local_generate,
)

logger = logging.getLogger(__name__)

# 没有现成计费表条目,同 identity_pack.py 里 _VIDU_TURNAROUND_COST_ESTIMATE_USD 的惯例
# 保守估个量级:fal-ai/flux/schnell 官方约 $0.003/张。
_FAL_IMAGE_COST_ESTIMATE_USD = 0.01

# 本地 CPU 兜底档位:2026-07-09 在这台 20 核机器上实测过,512×512/25 步(配合英文
# prompt)单张约 190-220s,能稳定出可用的历史人物内容——1024×1024/30 步(GPU 默认档)
# 在 CPU 上外推要 15-20 分钟/张,对一次身份包构建(~17 张/角色)完全不现实。免费但慢,
# 排在云端 fal.ai 之前(见模块 docstring)。
_CPU_FALLBACK_WIDTH = 512
_CPU_FALLBACK_HEIGHT = 512
_CPU_FALLBACK_STEPS = 25


def _cpu_downgrade(req: dict[str, Any]) -> dict[str, Any]:
    """把一个生成请求(sdxl_local_generate_batch 的 dict 形状)降配到 CPU 可承受的
    分辨率/步数,output_path/seed/prompt 等其余字段原样保留。
    """
    downgraded = dict(req)
    downgraded["width"] = _CPU_FALLBACK_WIDTH
    downgraded["height"] = _CPU_FALLBACK_HEIGHT
    extra = dict(downgraded.get("extra") or {})
    extra.setdefault("num_inference_steps", _CPU_FALLBACK_STEPS)
    downgraded["extra"] = extra
    return downgraded


# 一次网络抖动不该直接判这张图失败,但也不无限重试——重试耗尽就放弃这张图。
_FALLBACK_RETRIES = 2
_FALLBACK_RETRY_BACKOFF_S = 3.0

# 缺 key / 账户欠费封锁这类错误重试多少次结果都一样——命中就直接放弃,不空转
# (_FALLBACK_RETRIES+1)*backoff 秒。字符串匹配跟 fal_image_service.py 里实际抛出的
# 错误文案对齐,不是猜的。
_NON_RETRYABLE_MARKERS = ("not configured", "Exhausted balance", " 403", " 401")


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc)
    return not any(marker in msg for marker in _NON_RETRYABLE_MARKERS)


async def _with_retries(
    fn: Callable[[], Awaitable[dict[str, Any]]],
    *,
    label: str,
    retries: int = _FALLBACK_RETRIES,
) -> dict[str, Any]:
    last_exc: Exception = RuntimeError(f"{label}: no attempts made")
    for attempt in range(retries + 1):
        try:
            return await fn()
        except Exception as e:
            last_exc = e
            if not _is_retryable(e):
                logger.info("%s 判定为不可重试错误,不再重试: %s", label, e)
                break
            if attempt < retries:
                delay = _FALLBACK_RETRY_BACKOFF_S * (attempt + 1)
                logger.warning("%s 第 %d 次尝试失败(%s),%.0fs 后重试", label, attempt + 1, e, delay)
                await asyncio.sleep(delay)
    raise last_exc


async def _cloud_fallback(
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    output_path: Path,
    seed: int | None,
    cost_limit: CostLimit | None,
    cost_tracker: CostTracker,
) -> dict[str, Any]:
    from hevi.image.fal_image_service import fal_image_generate

    await cost_tracker.check_and_reserve(_FAL_IMAGE_COST_ESTIMATE_USD, cost_limit)
    return await _with_retries(
        lambda: fal_image_generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            output_path=output_path,
            seed=seed,
        ),
        label="fal_image",
    )


async def resilient_image_gen(
    *,
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    output_path: Path | str,
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
    cost_limit: CostLimit | None = None,
    cost_tracker: CostTracker | None = None,
    **_: Any,
) -> dict[str, Any]:
    """ImageGenCaller 形状:本地 GPU 探活+生成失败就先降级本地 CPU(免费,降分辨率/
    步数),CPU 也失败才降级到 fal.ai 云端兜底(真花钱)——单张图独立判断,不因为一张
    图撞见 GPU 故障就放弃整批。

    cost_tracker 不传时退化成"只查这一笔"(每次调用都是全新的 CostTracker());
    调用方要拦住"很多张便宜图叠加超支",得在同一个 run 里复用同一个 CostTracker 实例
    (见 hevi.cost.circuit_breaker.CostTracker)。
    """
    output_path = Path(output_path)
    tracker = cost_tracker or CostTracker()

    try:
        await check_gpu_available()
        return await sdxl_local_generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            output_path=output_path,
            seed=seed,
            extra=extra,
        )
    except GPUUnavailableError as e:
        logger.warning("resilient_image_gen: 本地 GPU 不可用(%s),先试本地 CPU 兜底", e)
    except Exception as e:
        logger.warning("resilient_image_gen: 本地 SDXL 生成失败(%s),先试本地 CPU 兜底", e)

    try:
        cpu_extra = dict(extra or {})
        cpu_extra.setdefault("num_inference_steps", _CPU_FALLBACK_STEPS)
        return await sdxl_local_generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=_CPU_FALLBACK_WIDTH,
            height=_CPU_FALLBACK_HEIGHT,
            output_path=output_path,
            seed=seed,
            extra=cpu_extra,
            require_gpu=False,
        )
    except Exception as e:
        logger.warning("resilient_image_gen: 本地 CPU 兜底也失败(%s),降级到云端", e)

    return await _cloud_fallback(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        output_path=output_path,
        seed=seed,
        cost_limit=cost_limit,
        cost_tracker=tracker,
    )


# 云端兜底一张图动辄几秒到几十秒(fal.ai 是提交/轮询的队列模型),批量降级时不限流
# 并发就是拿云端 API 账户的 rate limit 硬撞;这个值只是"比完全串行快,又不至于一次性
# 把整批甩过去"的折中,不是哪家 API 文档量出来的精确值。
_FALLBACK_CONCURRENCY = 3


async def resilient_image_gen_batch(
    requests: list[dict[str, Any]],
    *,
    cost_limit: CostLimit | None = None,
    cost_tracker: CostTracker | None = None,
    fallback_concurrency: int = _FALLBACK_CONCURRENCY,
) -> list[dict[str, Any] | Exception]:
    """sdxl_local_generate_batch 形状的批量版兜底:GPU 健康时整批走一次本地 SDXL 子
    进程(模型只加载一次——这是 sdxl_local_generate_batch 本来的设计目的,per-image
    的 resilient_image_gen 为了能逐张探活/降级反而放弃了这个优势,见该函数 docstring)。

    批内单张失败或 GPU 探活直接不健康的图,先整批丢给本地 CPU 兜底(同样一次性批量
    加载模型,免费但降分辨率/步数换时间——见 _cpu_downgrade),CPU 那批里还失败的才
    最后逐张降级到云端(真花钱),不因为一张图失败就把整批都丢给云端。
    """
    if not requests:
        return []

    from hevi.image.sdxl_local_service import sdxl_local_generate_batch

    results: list[dict[str, Any] | Exception]
    need_fallback: list[int]

    try:
        await check_gpu_available()
        results = await sdxl_local_generate_batch(requests)
        need_fallback = [i for i, r in enumerate(results) if isinstance(r, Exception)]
        if need_fallback:
            logger.warning(
                "resilient_image_gen_batch: 本地批量生成 %d/%d 张失败,尝试 CPU 兜底",
                len(need_fallback),
                len(requests),
            )
    except GPUUnavailableError as e:
        logger.warning("resilient_image_gen_batch: 本地 GPU 不可用(%s),整批降级到 CPU", e)
        results = [e] * len(requests)
        need_fallback = list(range(len(requests)))
    except Exception as e:
        logger.warning("resilient_image_gen_batch: 本地批量生成失败(%s),整批降级到 CPU", e)
        results = [e] * len(requests)
        need_fallback = list(range(len(requests)))

    if not need_fallback:
        return results

    try:
        cpu_requests = [_cpu_downgrade(requests[i]) for i in need_fallback]
        cpu_results = await sdxl_local_generate_batch(cpu_requests, require_gpu=False)
        still_need_fallback = []
        for idx, r in zip(need_fallback, cpu_results, strict=True):
            if isinstance(r, Exception):
                still_need_fallback.append(idx)
            else:
                results[idx] = r
        if still_need_fallback:
            logger.warning(
                "resilient_image_gen_batch: CPU 兜底仍有 %d/%d 张失败,逐张降级到云端",
                len(still_need_fallback),
                len(need_fallback),
            )
        need_fallback = still_need_fallback
    except Exception as e:
        logger.warning("resilient_image_gen_batch: CPU 批量兜底整体失败(%s),逐张降级到云端", e)

    if not need_fallback:
        return results

    tracker = cost_tracker or CostTracker()
    semaphore = asyncio.Semaphore(max(1, fallback_concurrency))

    async def _fallback_one(i: int) -> None:
        req = requests[i]
        async with semaphore:
            try:
                results[i] = await _cloud_fallback(
                    prompt=req["prompt"],
                    negative_prompt=req.get("negative_prompt") or "",
                    width=req.get("width", 1024),
                    height=req.get("height", 1024),
                    output_path=Path(req["output_path"]),
                    seed=req.get("seed"),
                    cost_limit=cost_limit,
                    cost_tracker=tracker,
                )
            except Exception as e:
                results[i] = e

    await asyncio.gather(*(_fallback_one(i) for i in need_fallback))
    return results
