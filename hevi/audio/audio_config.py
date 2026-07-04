from enum import StrEnum


class AudioProvider(StrEnum):
    EDGE_TTS = "edge_tts"  # 多语言云 TTS(默认,不占 GPU、无需模型)
    LTX2_NATIVE = "ltx2_native"  # LTX-2 原生音视频(内核已含,音频层不处理)
    VIBEVOICE = "vibevoice"  # 多说话人本地配音(需 vibevoice-1.5b 模型)
    DUIX = "duix"  # 数字人口播
