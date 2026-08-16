"""h3_local —— MiniMax H3 本地视频 provider(ComfyUI,8GB)+ 镜头级后处理。"""

from hevi.providers.h3_local.comfy_client import (
    ComfyClient,
    H3ComfyError,
    h3_length_for_duration,
)
from hevi.providers.h3_local.provider import (
    H3_LOCAL_CAPABILITY,
    h3_local_generate,
    register_h3_local,
)

__all__ = [
    "H3_LOCAL_CAPABILITY",
    "ComfyClient",
    "H3ComfyError",
    "h3_length_for_duration",
    "h3_local_generate",
    "register_h3_local",
]
