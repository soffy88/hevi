"""成本感知路由 v1(SSOT §7-2)。

在(能力 ⊇ 需求 ∧ 活状态可路由 ∧ 质量 ≥ floor)的 video provider 中选 **min(cost)**。
组合三件已有件:
  - `video.capability_guard.PROVIDER_LIMITS` —— 能力(哪些 provider 支持该 mode)
  - `resilience.live_state.provider_routable` —— 活状态(跳过欠费/被锁,C5 接线)
  - `cost.selector.select_cheapest_provider` —— 质量下限 + 最便宜(复活的死代码)

v1 为**任务级**(`video_provider="auto"` 时解析)。镜头级路由(主角特写→Kling、空镜→本地 Wan)
待 per-shot 质量需求元数据落地后再做 —— 见 SSOT §3 L0。

lip-sync 作为可路由能力(HEVI 路线图 Phase3 #42):`PROVIDER_LIMITS` 已有 `lip_sync`
列(#35),这里加 `require_lip_sync` 筛选。路线图设想的是"在'生成+后处理'与'原生
音画 provider'间按成本选"——但这次核实后确认 hevi 里**没有任何 lip-sync 后处理
实现**(`hevi/cinematic/schemas.py` 的 `lipsync_note` 明确标"not implemented"),
"不作为独立功能开发"意味着这次不该借这个任务顺手做一个——所以目前 `require_lip_sync`
只会筛出**原生**支持的 provider(现在就是 veo3);后处理路径一旦真的实现,只需要
在能力矩阵里给对应 provider 也标 `lip_sync=True`,这里的筛选逻辑不用改。
"""

from __future__ import annotations

import logging

from hevi.cost.selector import select_cheapest_provider
from hevi.resilience.live_state import provider_routable
from hevi.video.capability_guard import PROVIDER_LIMITS

logger = logging.getLogger(__name__)


async def route_video_provider(
    *,
    duration_archetype: str,
    audio_provider: str,
    mode: str = "t2v",
    quality_floor: int = 9,
    candidates: list[str] | None = None,
    require_lip_sync: bool = False,
) -> str:
    """选 video provider:支持 `mode`(+ 可选 lip_sync)∧ 活状态可路由 ∧
    质量≥`quality_floor` 中最便宜。

    quality_floor:质量下限(北极星"质量有下限")。默认 9 = 只在高质量云档里选便宜的;
    降低它可纳入零成本本地 Wan(economy/空镜)。无合格者 → ValueError(调用方回退用户所选)。
    """
    pool = candidates or [p for p, lim in PROVIDER_LIMITS.items() if mode in lim.modes]
    if require_lip_sync:
        pool = [p for p in pool if PROVIDER_LIMITS.get(p) and PROVIDER_LIMITS[p].lip_sync]
    routable = [p for p in pool if provider_routable(p)]
    if not routable:
        raise ValueError(
            f"no routable video provider for mode={mode!r}"
            + (" with lip_sync" if require_lip_sync else "")
        )
    chosen = await select_cheapest_provider(
        duration_archetype=duration_archetype,
        candidates=routable,
        audio_provider=audio_provider,
        quality_floor=quality_floor,
    )
    logger.info(
        "routed video provider=%s (mode=%s, floor=%d, lip_sync=%s, %d routable candidates)",
        chosen,
        mode,
        quality_floor,
        require_lip_sync,
        len(routable),
    )
    return chosen
