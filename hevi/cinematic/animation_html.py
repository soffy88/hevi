"""animation_html —— 黄金公式分镜的 HTML/CSS 动画渲染 (零 API 额度兜底)。

文生视频 provider (阿里 wan_2_7 免费额度耗尽 / WaveSpeed 无 key) 时降级:
每镜渲染一张 HTML 动画卡片 —— 黄金公式字段视觉化:
  * 景别 (shot_size)   → 字号层级 (wide=全景小字 / close=特写大字)
  * 运镜 (movement)    → CSS keyframes (push_in=推近 / pull_out=拉远 / pan=横移 / tracking=跟随)
  * 氛围+光线          → 背景渐变 + 光效层 (日光/暖阳/侧光/柔和)
  * 情绪 (emotion)     → emoji + 强调色 (笑😊 慌😱 专注🤔 坚定💪 温馨🥰)
旁白 `<audio>` 挂页内 → playwright 音频驱动录屏 → 时长天然对齐。

不开天窗哲学: provider 全失败也有动画可出片。
"""

from __future__ import annotations

import base64
from pathlib import Path

from hevi.cinematic.golden_formula import GoldenBeat

# 情绪关键词 → emoji + 强调色
_EMOTION_MAP: list[tuple[str, str, str]] = [
    ("欢", "😊", "#ffd27d"), ("笑", "😊", "#ffd27d"), ("乐", "😄", "#ffd27d"),
    ("慌", "😱", "#7f9cf5"), ("恐", "😱", "#7f9cf5"), ("惊", "😱", "#7f9cf5"),
    ("坚定", "💪", "#f9a825"), ("专注", "🤔", "#90cdf4"),
    ("疑", "🤨", "#c3b8f5"), ("暖", "🥰", "#ffb3c1"), ("温馨", "🥰", "#ffb3c1"),
    ("赞", "👍", "#7fd1a5"), ("怒", "😠", "#f56565"), ("平静", "😌", "#a0aec0"),
]

# 氛围关键词 → 背景渐变
_ATMOSPHERE_GRADIENTS: list[tuple[str, str]] = [
    ("轻松", "linear-gradient(160deg,#ffe8b3,#ffd27d)"),
    ("温馨", "linear-gradient(160deg,#ffe0e6,#ffb3c1)"),
    ("祥和", "linear-gradient(160deg,#fff3d6,#ffd9a0)"),
    ("紧张", "linear-gradient(160deg,#3b4252,#2c3343)"),
    ("危急", "linear-gradient(160deg,#4a3b3b,#2f2626)"),
    ("危机", "linear-gradient(160deg,#4a3b3b,#2f2626)"),
    ("惊慌", "linear-gradient(160deg,#39425e,#232a3d)"),
    ("疑惑", "linear-gradient(160deg,#4a4658,#2f2c3a)"),
    ("郑重", "linear-gradient(160deg,#3f4a5a,#26303f)"),
    ("静谧", "linear-gradient(160deg,#d9e4ec,#b7c9d9)"),
    ("期待", "linear-gradient(160deg,#fff0c2,#ffe29a)"),
    ("专注", "linear-gradient(160deg,#dbe7f5,#b8cfe8)"),
]

# 光线关键词 → 光效层 CSS
_LIGHTING_LAYERS: list[tuple[str, str]] = [
    ("日光", "radial-gradient(circle at 30% 0%, rgba(255,240,180,.55), transparent 55%)"),
    ("暖阳", "radial-gradient(circle at 60% 10%, rgba(255,200,120,.5), transparent 60%)"),
    ("暖光", "radial-gradient(circle at 40% 0%, rgba(255,180,100,.45), transparent 55%)"),
    ("侧光", "linear-gradient(90deg, rgba(255,255,255,.35), transparent 45%, transparent)"),
    ("柔和", "radial-gradient(circle at 50% 40%, rgba(255,255,255,.3), transparent 70%)"),
    ("水花", "radial-gradient(circle at 30% 70%, rgba(140,190,255,.5), transparent 55%)"),
]

# 运镜 → CSS keyframes
_MOVEMENT_KF: dict[str, str] = {
    "push_in": "@keyframes cam { from { transform: scale(1); } to { transform: scale(1.32); } }",
    "pull_out": "@keyframes cam { from { transform: scale(1.32); } to { transform: scale(1); } }",
    "pan": "@keyframes cam { from { transform: translateX(3%); } to { transform: translateX(-3%); } }",
    "tracking": "@keyframes cam { from { transform: translateX(2%) scale(1.05); } to { transform: translateX(-2%) scale(1.05); } }",
    "static": "@keyframes cam { from { transform: scale(1.02); } to { transform: scale(1.0); } }",
}

# 景别 → 字号/版式
_SHOT_SIZE_STYLE: dict[str, str] = {
    "wide": "font-size: clamp(48px, 9vw, 92px); text-align: center;",
    "full": "font-size: clamp(52px, 10vw, 100px); text-align: center;",
    "medium": "font-size: clamp(56px, 11vw, 112px); text-align: center;",
    "medium_close": "font-size: clamp(64px, 12vw, 128px); text-align: center;",
    "close": "font-size: clamp(72px, 14vw, 148px); text-align: center;",
    "extreme_close": "font-size: clamp(88px, 16vw, 172px); text-align: center;",
}


def _bg_gradient(atmosphere: str) -> str:
    for kw, grad in _ATMOSPHERE_GRADIENTS:
        if kw in atmosphere:
            return grad
    return "linear-gradient(160deg,#e8ecf1,#cbd5e0)"


def _light_layer(lighting: str) -> str:
    for kw, layer in _LIGHTING_LAYERS:
        if kw in lighting:
            return layer
    return ""


def _emotion_for(text: str) -> tuple[str, str]:
    for kw, emoji, color in _EMOTION_MAP:
        if kw in text:
            return emoji, color
    return "✨", "#ffffff"


def golden_beat_html(beat: GoldenBeat, narration_audio: Path | None) -> str:
    """一镜 HTML 卡片: 黄金公式字段 → 视觉化。narration_audio 挂音频驱动时长。"""
    bg = _bg_gradient(beat.atmosphere)
    light = _light_layer(beat.lighting)
    emoji, _accent = _emotion_for(f"{beat.emotion_expression} {beat.atmosphere}")
    kf = _MOVEMENT_KF.get(beat.movement, _MOVEMENT_KF["static"])
    size_style = _SHOT_SIZE_STYLE.get(beat.shot_size, _SHOT_SIZE_STYLE["medium"])

    lines = [beat.subject, beat.action]
    if beat.emotion_expression:
        lines.append(beat.emotion_expression)
    body = "".join(f'<div class="line">{ln}</div>' for ln in lines if ln)

    audio_tag = ""
    audio_js = ""
    if narration_audio and narration_audio.exists():
        data_uri = (
            "data:audio/mpeg;base64,"
            + base64.b64encode(narration_audio.read_bytes()).decode()
        )
        audio_tag = f'<audio id="nar" src="{data_uri}" autoplay></audio>'
        audio_js = (
            "var a=document.getElementById('nar');"
            "a.addEventListener('ended',function(){"
            "window.__heviAudioEnded=true;});"
            "setTimeout(function(){window.__heviAudioEnded=true;},"
            f"{max(4000, int(beat.duration_s * 1000))});"
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  html,body{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;
    background:{bg};font-family:'Noto Sans SC','PingFang SC',sans-serif;}}
  .stage{{position:relative;width:100%;height:100%;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:3vh;padding:6vh 6vw;box-sizing:border-box;}}
  {kf}
  .cam{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
    justify-content:center;gap:3vh;animation:cam {max(beat.duration_s, 4.0)}s ease-in-out both;}}
  .line{{color:#2d3748;font-weight:800;line-height:1.35;{size_style}
    text-shadow:0 2px 10px rgba(255,255,255,.5);}}
  .emoji{{font-size:clamp(64px,12vw,140px);filter:drop-shadow(0 6px 14px rgba(0,0,0,.25));}}
  .light{{position:absolute;inset:0;pointer-events:none;{('background:' + light) if light else ''}}}
  .foot{{position:absolute;bottom:6vh;width:100%;text-align:center;
    color:rgba(45,55,72,.55);font-size:clamp(20px,4vw,34px);font-weight:600;}}
</style></head><body>
<div class="stage">
  <div class="cam">
    <div class="emoji">{emoji}</div>
    {body}
    <div class="foot">{beat.atmosphere} · {beat.lighting}</div>
  </div>
  <div class="light"></div>
</div>
{audio_tag}
<script>{audio_js}</script>
</body></html>"""


async def render_html_shot(
    beat: GoldenBeat,
    html_dir: Path,
    out: Path,
    *,
    narration_audio: Path | None = None,
    width: int = 720,
    height: int = 1280,
) -> Path:
    """渲染一镜 HTML 动画 → 录屏成视频 (音频驱动时长)。"""
    from hevi.pipeline_lite.oprim.oprim_playwright import record_html_to_video

    html_dir = Path(html_dir)
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / f"beat_{beat.index:02d}.html"
    html_path.write_text(golden_beat_html(beat, narration_audio), encoding="utf-8")
    return await record_html_to_video(
        html_path, out, width=width, height=height, fps=24,
        duration_s=beat.duration_s, scroll=False,
    )


__all__ = ["golden_beat_html", "render_html_shot"]
