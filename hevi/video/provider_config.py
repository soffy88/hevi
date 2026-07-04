from enum import StrEnum


class VideoProvider(StrEnum):
    LTX2_CLOUD = "ltx2_cloud"
    LTX2_LOCAL = "ltx2_local"  # 本地推理,路由到 wan_local(本机唯一 GPU 推理实现)
    WAN_CLOUD = "wan_cloud"
    WAN_LOCAL = "wan_local"
    # 高写实云档(fal):真人/手部/面部远优于 ltx2 基础版
    VEO3 = "veo3"  # Google Veo 3,写实最佳 + 原生音频
    KLING_V2 = "kling_v2"  # 快手可灵 v2 master
    HAILUO = "hailuo"  # MiniMax 海螺 02


# 支持 negative_prompt / aspect_ratio 的高写实云 provider(hevi 侧路由概念:
# injected_video_fn 据此对这些 provider 下发负向词与朝向)。原语已迁 oprim,
# 但"哪些 provider 走这条下发路径"属应用层路由,留在 hevi。
FAL_PREMIUM_PROVIDERS = frozenset({"veo3", "kling_v2", "hailuo"})
