from hevi.cost.estimator import estimate_cost

# Simple quality tiers: 0 to 10。覆盖全部 7 个 video provider(+ 音频),供成本感知路由过滤。
# HEVI 路线图 Phase2 #35 评估过:这张表是人工按实际出片质量口碑定的,不是从
# capability_guard.py 的规格字段(分辨率/时长/native_audio 等)机械派生的——质量
# 好坏不是规格的线性函数(同样 1080p,veo3 的解剖学真实感明显强于 wan_cloud),
# 没有真实的输出质量基准数据前不应该拿公式替换人工判断,故保留手工维护。
PROVIDER_QUALITY = {
    # video
    "ltx2_cloud": 10,
    "veo3": 10,  # 真人/解剖最佳 + 原生音频
    "wan_cloud": 9,
    "kling_v2": 9,
    "hailuo": 8,
    "wan_local": 7,  # 零成本本地,质量档较低
    "ltx2_local": 7,
    # WaveSpeed AI:刚接入(2026-07),没有实际出片口碑数据——初始估值,不是基准测过的
    # 分数,待有真实产出后按同样的手工口碑方式重新校准。wan_2_7 参照同宗 wan_cloud
    # 的既有档位;happyhorse_1_1 官方自称旗舰但 native_audio/lip_sync 未经 API 契约
    # 证实(见 capability_guard.py 注释),暂不比照 veo3(10)那一档。
    "happyhorse_1_1": 9,
    "wan_2_7": 9,
    # 同一对模型,阿里官方直连(2026-07 接入):同样没有实际出片口碑数据,估值原样
    # 照抄 WaveSpeed 那两条——是不是同一档要等两边都有真实产出数据再各自校准,不能
    # 假设"官方直连=质量更高"。
    "happyhorse_1_1_maas": 9,
    "wan_2_7_maas": 9,
    # audio
    "vibevoice": 8,
    "duix": 8,
}


async def select_cheapest_provider(
    *,
    duration_archetype: str,
    candidates: list[str],
    audio_provider: str,
    quality_floor: int = 9,
) -> str:
    """Select the cheapest provider that meets the quality floor.

    'Quality is King': we only consider candidates above quality_floor.
    """
    eligible = [c for c in candidates if PROVIDER_QUALITY.get(c, 0) >= quality_floor]

    if not eligible:
        raise ValueError(f"No providers meet the quality floor of {quality_floor}")

    costs = []
    for provider in eligible:
        estimate = await estimate_cost(
            duration_archetype=duration_archetype,
            video_provider=provider,
            audio_provider=audio_provider,
        )
        costs.append((provider, estimate.total_usd))

    # Sort by cost ascending
    costs.sort(key=lambda x: x[1])
    return costs[0][0]
