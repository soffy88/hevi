"""镜头级成本路由 route v2(设计 §3 L0)—— 逐镜头按需求选 provider。

设计:"主角特写镜头走 Kling(参考图一致性好),空镜 B-roll 走本地 Wan(零成本)"——单
provider 产品做不到的成本结构。per-shot 质量需求从镜头 **prompt** 启发式分类得到(无需额外
元数据):高需求(主角/特写/人物)→ 高质量档(云);低需求(空镜/风景/远景)→ 低档(可用
零成本本地 wan)。再交给 route_video_provider(能力×活状态×最便宜)。
"""

from __future__ import annotations

from hevi.cost.router import route_video_provider

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
) -> str:
    """单镜头选 provider:按 prompt 判质量需求 → route_video_provider(能力×活状态×最便宜)。

    require_lip_sync(HEVI 路线图 Phase3 #42):这个镜头有对白/需要对口型时传 True,
    只在原生支持 lip_sync 的 provider 里选(目前只有 veo3——hevi 没有 lip-sync 后处理
    实现,不假装能路由到别的)。
    """
    floor = classify_shot_quality_floor(prompt, default=default_floor)
    return await route_video_provider(
        duration_archetype=duration_archetype,
        audio_provider=audio_provider,
        mode=mode,
        quality_floor=floor,
        require_lip_sync=require_lip_sync,
    )
