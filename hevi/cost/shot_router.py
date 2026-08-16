"""镜头级成本路由 route v2(设计 §3 L0)—— 逐镜头按需求选 provider。

设计:"主角特写镜头走 Kling(参考图一致性好),空镜 B-roll 走本地 Wan(零成本)"——单
provider 产品做不到的成本结构。per-shot 质量需求从镜头 **prompt** 启发式分类得到(无需额外
元数据):高需求(主角/特写/人物)→ 高质量档(云);低需求(空镜/风景/远景)→ 低档(可用
零成本本地 wan)。再交给 route_video_provider(能力×活状态×最便宜)。
"""

from __future__ import annotations

import logging
import os

from hevi.cost.router import route_video_provider

logger = logging.getLogger(__name__)

# 关键词启发(中英)。低需求 → 降 floor 纳入免费本地;高需求 → 抬 floor 只上高质量云。
_LOW_NEED = (
    "空镜",
    "风景",
    "远景",
    "全景",
    "b-roll",
    "broll",
    "landscape",
    "establishing",
    "scenery",
    "wide shot",
    "aerial",
)
_HIGH_NEED = (
    "主角",
    "特写",
    "人物",
    "脸",
    "面部",
    "close-up",
    "closeup",
    "portrait",
    "character",
    "hero",
    "face",
    "protagonist",
)
#: 中文对白镜标记(H3 提示词包结构;命中即偏好 zh prompt 的本地 H3)。
_ZH_DIALOGUE_MARKERS = ("【对白】", "<d>[Chinese]", "说道：", "说道:")
#: H3 本地质量档(selector.PROVIDER_QUALITY)——economy 档(floor ≤ 此值)可纳入。
_H3_LOCAL_QUALITY = 7


def _prefer_h3_local(prompt: str, floor: int, override: str) -> bool:
    """路由规则:economy / 中文对白镜 → 优先 h3_local(H3_ROUTING 可显式开关)。

    - H3_ROUTING=off:永不(矩阵里可关可降级)。
    - H3_ROUTING=on:只要活状态可路由就选。
    - auto(默认):floor ≤ 7(economy/空镜)或 prompt 带中文对白标记 → 选。
    """
    if override == "off":
        return False
    if override == "on":
        return True
    if floor <= _H3_LOCAL_QUALITY:
        return True
    p = prompt or ""
    return any(m in p for m in _ZH_DIALOGUE_MARKERS)


def classify_shot_quality_floor(prompt: str, *, default: int = 9) -> int:
    """镜头 prompt → 质量下限。低需求空镜→7(可用免费本地 wan);高需求主角特写→10(只上云)。"""
    p = (prompt or "").lower()
    if any(k in p for k in _LOW_NEED):
        return 7
    if any(k in p for k in _HIGH_NEED):
        return 10
    return default


async def route_shot_provider(
    *,
    prompt: str,
    duration_archetype: str,
    audio_provider: str,
    mode: str = "t2v",
    default_floor: int = 9,
    require_lip_sync: bool = False,
    prefer_h3_local: bool | None = None,
) -> str:
    """单镜头选 provider:按 prompt 判质量需求 → route_video_provider(能力×活状态×最便宜)。

    require_lip_sync(HEVI 路线图 Phase3 #42):这个镜头有对白/需要对口型时传 True,
    只在原生支持 lip_sync 的 provider 里选(目前只有 veo3——hevi 没有 lip-sync 后处理
    实现,不假装能路由到别的)。

    prefer_h3_local:None=按 H3_ROUTING(auto/on/off)与启发规则;True/False 显式钉死。
    规则:economy 档(floor ≤ 7)或中文对白镜 → 优先本地 H3(零成本 + 原生中文音频);
    高需求/长单镜/复杂物理 → 照常走云。
    """
    floor = classify_shot_quality_floor(prompt, default=default_floor)
    override = os.getenv("H3_ROUTING", "auto")
    want_h3 = (
        _prefer_h3_local(prompt, floor, override) if prefer_h3_local is None else prefer_h3_local
    )
    if want_h3:
        from hevi.cost.selector import PROVIDER_QUALITY
        from hevi.resilience.live_state import provider_routable

        if provider_routable("h3_local") and PROVIDER_QUALITY.get("h3_local", 0) >= floor:
            logger.info(
                "route v2: 偏好 h3_local(economy/中文对白,H3_ROUTING=%s, floor=%d)",
                override,
                floor,
            )
            return "h3_local"
        logger.info("route v2: 偏好 h3_local 但不可路由,回落常规路由")
    return await route_video_provider(
        duration_archetype=duration_archetype,
        audio_provider=audio_provider,
        mode=mode,
        quality_floor=floor,
        require_lip_sync=require_lip_sync,
    )
