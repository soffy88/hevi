from hevi.cost.estimator import estimate_cost

# Simple quality tiers: 0 to 10。覆盖全部 7 个 video provider(+ 音频),供成本感知路由过滤。
PROVIDER_QUALITY = {
    # video
    "ltx2_cloud": 10,
    "veo3": 10,  # 真人/解剖最佳 + 原生音频
    "wan_cloud": 9,
    "kling_v2": 9,
    "hailuo": 8,
    "wan_local": 7,  # 零成本本地,质量档较低
    "ltx2_local": 7,
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
