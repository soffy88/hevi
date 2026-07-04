"""hevi 翻译配音导出(设计 §3 L2)—— Series"出 X 语种版"。

ASR(faster-whisper)→ translate_cues(本地 qwen)→ edge-tts 目标语种 → mux。
"""

from hevi.dub.translate import dub_video, translate_cues

__all__ = ["dub_video", "translate_cues"]
