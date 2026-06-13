from enum import StrEnum


class AudioProvider(StrEnum):
    LTX2_NATIVE = "ltx2_native"  # LTX-2 原生音视频(内核已含,音频层不处理)
    VIBEVOICE = "vibevoice"  # 多说话人配音
    DUIX = "duix"  # 数字人口播
