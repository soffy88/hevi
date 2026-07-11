"""hevi.explainer —— 自媒体解说短视频通道:选题 → 文案分镜 → 配音 → Remotion 渲染。

E0 storyboard(LLM 生成 6 段固定结构文案+画面参数)→ E1 gate_storyboard(结构校验)→
E2 voiceover(edge-tts 配音 + 词级时间戳字幕)→ E3 render(Remotion 出竖屏/横屏 MP4)。

6 种 sceneType 固化自"沉没成本"首个真实交付(hevi-remotion/src/scenes/*.tsx),
不是任意结构——hook/definition/cards/reason/method/outro 顺序固定。
"""

from hevi.explainer.render import RenderResult, render_storyboard
from hevi.explainer.schemas import (
    CaptionCue,
    GateResult,
    ManifestSegment,
    Storyboard,
    StoryboardSegment,
)
from hevi.explainer.storyboard import gate_storyboard, generate_storyboard
from hevi.explainer.voiceover import VoiceoverError, synthesize_storyboard

__all__ = [
    "CaptionCue",
    "GateResult",
    "ManifestSegment",
    "RenderResult",
    "Storyboard",
    "StoryboardSegment",
    "VoiceoverError",
    "gate_storyboard",
    "generate_storyboard",
    "render_storyboard",
    "synthesize_storyboard",
]
