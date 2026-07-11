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
    # 参考图锁脸(reference-to-video)通道:hevi/providers/registry.py 已注册,
    # 这里补全枚举——否则 build_longvideo_config 会拒绝这些合法 provider 名。
    VIDU = "vidu"  # Vidu Reference-to-Video
    HAPPYHORSE_1_1 = "happyhorse_1_1"  # WaveSpeed 转售
    HAPPYHORSE_1_1_REF = "happyhorse_1_1_ref"  # WaveSpeed 转售,reference_images 版
    WAN_2_7 = "wan_2_7"  # WaveSpeed 转售
    HAPPYHORSE_1_1_MAAS = "happyhorse_1_1_maas"  # 阿里云百炼官方直连
    HAPPYHORSE_1_1_MAAS_REF = "happyhorse_1_1_maas_ref"  # 阿里云百炼官方直连,reference_images 版
    # 主线管线(create_episode/Series/orchestrate_longvideo)专用单参考图版,见
    # hevi/video/alibaba_maas_service.py::happyhorse_1_1_maas_lock_generate 顶部注释。
    HAPPYHORSE_1_1_MAAS_LOCK = "happyhorse_1_1_maas_lock"
    WAN_2_7_MAAS = "wan_2_7_maas"  # 阿里云百炼官方直连


# 支持 negative_prompt / aspect_ratio 的高写实云 provider(hevi 侧路由概念:
# injected_video_fn 据此对这些 provider 下发负向词与朝向)。原语已迁 oprim,
# 但"哪些 provider 走这条下发路径"属应用层路由,留在 hevi。
FAL_PREMIUM_PROVIDERS = frozenset({"veo3", "kling_v2", "hailuo"})
