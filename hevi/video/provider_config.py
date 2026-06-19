from enum import StrEnum


class VideoProvider(StrEnum):
    LTX2_CLOUD = "ltx2_cloud"
    LTX2_LOCAL = "ltx2_local"   # 本地推理,路由到 wan_local(本机唯一 GPU 推理实现)
    WAN_CLOUD = "wan_cloud"
    WAN_LOCAL = "wan_local"
