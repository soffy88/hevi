from typing import Any

from hevi.core.config import settings

# fal.ai LTX-2 真实二维单价 (tier × resolution), 美元/秒
# Source: fal.ai pricing page, calibrated 2026-06
LTX2_PRICING: dict[str, dict[str, float]] = {
    "fast": {
        "1080p": 0.04,
        "1440p": 0.08,
        "2160p": 0.16,
    },
    "pro": {
        "1080p": 0.06,
        "1440p": 0.12,
        "2160p": 0.24,
    },
}

# video_element_edit (retake) 端点单价, 美元/秒
LTX2_RETAKE_PER_SECOND: float = 0.10

DEFAULT_LTX2_TIER: str = "fast"

# fal.ai endpoint URLs — switched via M1 config dict key "FAL_BASE_URL".
# NOTE: M1 ltx2_cloud_generate has no tier param; we pass the endpoint via config.
# Pro URL is a placeholder — confirm actual endpoint with fal.ai before enabling.
LTX2_ENDPOINTS: dict[str, str] = {
    "fast": "https://fal.run/fal-ai/ltx-video",
    "pro": "https://fal.run/fal-ai/ltx-video-pro",  # placeholder; verify with fal.ai
}

# DashScope Qwen token pricing (美元/1k tokens)
# Source: console.aliyun.com/billing — Qwen-Plus 2026-06 (TODO: re-verify quarterly)
# Input: ¥0.0008/1k → $0.00011; Output: ¥0.002/1k → $0.00028; blended ~$0.0002/1k
QWEN_DASHSCOPE_PRICE_PER_1K_TOKENS: float = 0.0002  # blended; TODO: split input/output


def get_ltx2_price_per_second(tier: str, resolution: str) -> float:
    """Return fal.ai LTX-2 price per second for (tier, resolution_key) pair."""
    tier_table = LTX2_PRICING.get(tier, LTX2_PRICING[DEFAULT_LTX2_TIER])
    return tier_table.get(resolution, tier_table["1080p"])


def get_pricing_table() -> dict[str, dict[str, Any]]:
    """Get current provider pricing table.

    ltx2_cloud: price_usd is the Fast-1080p default; use pricing_2d for
    resolution-aware billing or call get_ltx2_price_per_second() directly.
    wan_cloud: ¥0.24/s 720p; loaded from settings.wan_price_usd ($0.033/s).
    wan_local / qwen_local: $0 (local GPU, no API cost).
    qwen_dashscope: blended token price; TODO verify rate quarterly.
    """
    return {
        # --- video providers ---
        "ltx2_cloud": {
            "unit": "per_second",
            "price_usd": get_ltx2_price_per_second(DEFAULT_LTX2_TIER, "1080p"),
            "pricing_2d": LTX2_PRICING,
        },
        "wan_cloud": {
            "unit": "per_second",
            "price_usd": settings.wan_price_usd,
        },
        "wan_local": {
            "unit": "per_second",
            "price_usd": 0.0,
        },
        "ltx2_local": {
            "unit": "per_second",
            "price_usd": 0.0,
        },
        "ltx2_native": {
            "unit": "per_minute",
            "price_usd": 0.0,
        },
        # --- 高写实云档(fal,按秒近似)---
        "veo3": {  # Veo3 fast ≈ $0.40 / 8s
            "unit": "per_second",
            "price_usd": 0.05,
        },
        "kling_v2": {  # Kling v2 master ≈ $0.14 / 5s
            "unit": "per_second",
            "price_usd": 0.028,
        },
        "hailuo": {  # 海螺 02 standard ≈ $0.045 / 6s
            "unit": "per_second",
            "price_usd": 0.0075,
        },
        # --- WaveSpeed AI(阿里模型聚合网关)--- Source: wavespeed.ai 模型定价页,
        # 校准于 2026-07。720p 档位价;1080p 档更贵(happyhorse_1_1 $0.189/s,
        # wan_2_7 $0.15/s)——路由目前只按 720p 单价比较,还没做分辨率感知计费
        # (同 ltx2_cloud 的 pricing_2d 那套,这两个新 provider 暂沿用简单单价)。
        "happyhorse_1_1": {  # $0.70 / 5s @720p
            "unit": "per_second",
            "price_usd": 0.14,
        },
        "wan_2_7": {  # $0.50 / 5s @720p
            "unit": "per_second",
            "price_usd": 0.10,
        },
        # --- 阿里云百炼直连(alibaba_maas_service.py)--- 阿里官方定价页未核实到逐秒
        # 单价,沿用 WaveSpeed 转售价当上限估值(直连大概率更便宜,不会更贵)——
        # 这是"没有精确数据时保守估高"的占位,不是核实过的阿里官方价格,以后拿到
        # 真实账单再校准。
        "happyhorse_1_1_maas": {
            "unit": "per_second",
            "price_usd": 0.14,
        },
        "happyhorse_1_1_maas_lock": {  # 同 happyhorse_1_1_maas,单参考图锁脸窄接口
            "unit": "per_second",
            "price_usd": 0.14,
        },
        "wan_2_7_maas": {
            "unit": "per_second",
            "price_usd": 0.10,
        },
        # --- audio providers ---
        "edge_tts": {
            "unit": "per_minute",
            "price_usd": 0.0,  # 微软 Edge 神经语音免费
        },
        "vibevoice": {
            "unit": "per_minute",
            "price_usd": 0.0,
        },
        "duix": {
            "unit": "per_minute",
            "price_usd": 0.0,
        },
        # --- LLM providers ---
        "qwen_local": {
            "unit": "per_1k_tokens",
            "price_usd": 0.0,
        },
        "qwen_dashscope": {
            "unit": "per_1k_tokens",
            "price_usd": QWEN_DASHSCOPE_PRICE_PER_1K_TOKENS,
        },
    }
