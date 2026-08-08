"""oprim:oprim_html_gen —— HTML 合成原子能力(绝对无状态)。

只负责:把 JSON cue 数据 + 时间戳 + 模板字符串合成一个 HTML 文件,返回路径。
不涉及任何业务校验、状态写入、目录规划 —— 那都是 omodul 的职责。

v9.1 进阶(声音驱动画面 + 专业级动效):
  * 每张卡片 .slide 携带 data-start / data-end(秒), 来自 ASR 打轴;
  * CSS 过渡体系: 卡片默认 opacity:0 / translateY(30px), .is-active 用
    cubic-bezier(0.2, 0.8, 0.2, 1) 平滑滑入, .is-past 向上淡出;
  * 卡拉OK 词级高亮: 旁白按 whisper 词级时间戳拆成 <span class="word"
    data-start data-end>, JS 高亮当前词(.word.is-active, color 0.15s);
  * JS 引擎: requestAnimationFrame(≈16ms, ≪50ms) 句级+词级双层状态机,
    音频 onended → window.__heviAudioEnded = true 供 Playwright 收尾。
纯函数: 同输入必同输出。
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from hevi.pipeline_lite.schemas import LiteCue

_CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0f1220; font-family: -apple-system, "PingFang SC",
            "Microsoft YaHei", sans-serif; overflow-x: hidden; }}
  .slide {{ width: {width}px; height: {height}px; display: flex; flex-direction: column;
            justify-content: center; align-items: center; padding: 48px; color: #fff;
            position: relative;
            opacity: 0; transform: translateY(30px);
            transition: all 0.6s cubic-bezier(0.2, 0.8, 0.2, 1); }}
  .slide.is-active {{ opacity: 1; transform: translateY(0);
                      transition: all 0.6s cubic-bezier(0.2, 0.8, 0.2, 1); }}
  .slide.is-past {{ opacity: 0; transform: translateY(-30px);
                    transition: all 0.6s cubic-bezier(0.2, 0.8, 0.2, 1); }}
  .eyebrow {{ color: #7dd3fc; font-size: 22px; letter-spacing: 4px; margin-bottom: 18px; }}
  .title {{ font-size: 44px; font-weight: 800; line-height: 1.35;
             text-align: center; max-width: 80%; }}
  .narration {{ margin-top: 26px; font-size: 21px; line-height: 1.9; color: #64748b;
                max-width: 78%; text-align: center; }}
  /* 动态 B-roll 视频背景: 铺满底层 + 深色遮罩保证前景卡拉OK 可读性。 */
  .bg-video {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%;
               object-fit: cover; z-index: -1; filter: brightness(0.4);
               pointer-events: none; }}
  .slide {{ overflow: hidden; }}
  /* 卡拉OK 词级高亮: 未激活词灰度, 激活词纯白 + 光晕; 0.15s 跟手变色。 */
  .word {{ color: #94a3b8; transition: color 0.15s ease, text-shadow 0.15s ease; }}
  .word.is-active {{ color: #ffffff; text-shadow: 0 0 14px rgba(56, 189, 248, 0.75); }}
  .index {{ position: absolute; top: 24px; right: 32px; color: #475569; font-size: 18px; }}
  .progress {{ position: fixed; left: 0; bottom: 0; height: 5px; background: #38bdf8;
               transition: width 0.25s linear; z-index: 9; }}
</style>
</head>
<body>
<audio id="hevi-master" src="master_audio.wav" preload="auto"></audio>
{slides}
<div class="progress" id="hevi-progress"></div>
<script>
(function () {{
  window.__heviAudioEnded = false;
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var progress = document.getElementById('hevi-progress');
  var total = {total_ms};               // 毫秒: 由时间戳/兜底时长决定
  var audio = document.getElementById('hevi-master');
  var timer = null;
  var raf = null;
  var pollActive = false;
  var lastIdx = -1;
  var activeWordEl = null;

  function clearWord() {{
    if (activeWordEl) {{ activeWordEl.classList.remove('is-active'); activeWordEl = null; }}
  }}

  // ── 句级/词级双层状态机(requestAnimationFrame, ≈16ms ≪ 50ms) ──
  function tick() {{
    if (!pollActive) return;
    raf = requestAnimationFrame(tick);
    var t = audio.currentTime || 0;
    var idx = -1;
    var wordEl = null;
    for (var i = 0; i < slides.length; i++) {{
      var s = slides[i];
      var st = parseFloat(s.dataset.start || '0');
      var en = parseFloat(s.dataset.end || '0');
      var inWindow = (t >= st) && (t < en);
      s.classList.toggle('is-active', inWindow);
      // 离场: 音频已越过该句结束 → 向上淡出。
      s.classList.toggle('is-past', t >= en);
      if (inWindow && idx < 0) idx = i;
      if (inWindow && !wordEl) {{
        var words = s.querySelectorAll('.word');
        // 找「最后开始」的词: 词间空洞(停顿)保持前词高亮, 不闪烁。
        for (var j = 0; j < words.length; j++) {{
          var w = words[j];
          if (t >= parseFloat(w.dataset.start || st)) wordEl = w;
          else break;
        }}
      }}
    }}
    // 词级高亮只切换一次(性能: 每帧至多一次 class 翻转)。
    if (wordEl !== activeWordEl) {{
      clearWord();
      if (wordEl) wordEl.classList.add('is-active');
      activeWordEl = wordEl;
    }}
    if (idx !== lastIdx) {{
      lastIdx = idx;
      if (idx >= 0 && slides[idx].scrollIntoView) {{
        slides[idx].scrollIntoView({{ block: 'center', behavior: 'smooth' }});
      }}
    }}
    if (progress && audio.duration) progress.style.width = (t / audio.duration * 100) + '%';
  }}

  function endRecording() {{
    pollActive = false;
    if (raf) cancelAnimationFrame(raf);
    if (timer) clearInterval(timer);
    window.__heviAudioEnded = true;
    document.title = 'HEVI_AUDIO_ENDED';
    if (progress) progress.style.width = '100%';
  }}

  // 兜底: 无音频文件 / 播放异常时按计时器翻页(保持旧行为)。
  function startTimer() {{
    var per = Math.max(600, total / Math.max(slides.length, 1));
    var idx = 0; lastIdx = 0;
    slides.forEach(function (s, i) {{ s.classList.toggle('is-active', i === 0); }});
    if (slides[0] && slides[0].scrollIntoView) {{
      slides[0].scrollIntoView({{ block: 'center', behavior: 'smooth' }});
    }}
    timer = setInterval(function () {{
      idx += 1;
      if (idx >= slides.length) {{ endRecording(); return; }}
      lastIdx = idx;
      slides.forEach(function (s, i) {{
        s.classList.toggle('is-active', i === idx);
        s.classList.toggle('is-past', i < idx);
      }});
      if (slides[idx].scrollIntoView) {{
        slides[idx].scrollIntoView({{ block: 'center', behavior: 'smooth' }});
      }}
      if (progress) progress.style.width = ((idx + 1) / slides.length * 100) + '%';
    }}, per);
  }}

  if (audio) {{
    var bgVideos = Array.prototype.slice.call(document.querySelectorAll('video.bg-video'));
    var play = function () {{
      audio.play().catch(function () {{ /* autoplay 受限则计时器兜底 */ }});
    }};
    // B-roll 就绪门: 所有背景视频 loadeddata/首帧就绪后才允许主音频播放,
    // 避免录出黑屏或加载缓冲圈圈; 出错或超时(8s)则直接开播降级。
    function bgReady() {{
      return bgVideos.every(function (v) {{
        return v.error || v.readyState >= 2;   // HAVE_CURRENT_DATA
      }});
    }}
    function tryPlayWhenBgReady() {{
      if (bgReady()) {{ play(); return; }}
      var guard = setInterval(function () {{
        if (bgReady()) {{ clearInterval(guard); play(); }}
      }}, 200);
      setTimeout(function () {{
        clearInterval(guard);
        if (audio.paused) play();
      }}, 8000);
    }}
    audio.addEventListener('play', function () {{
      pollActive = true;
      requestAnimationFrame(tick);
    }});
    audio.addEventListener('ended', function () {{ endRecording(); }});
    audio.addEventListener('error', function () {{
      pollActive = false;
      if (raf) cancelAnimationFrame(raf);
      startTimer();
    }});
    // 看门狗: 音频时长异常(0/NaN)时计时器兜底, 防止录制永挂。
    audio.addEventListener('loadedmetadata', function () {{
      if (!isFinite(audio.duration) || audio.duration <= 0.05) startTimer();
    }});
    // 硬超时跟随真实音频时长(而非 data-end 估算), 防止打轴偏差提前截断录制。
    setTimeout(function () {{
      if (audio.duration && isFinite(audio.duration) && audio.duration > 0.5) {{
        setTimeout(endRecording, (audio.duration + 2) * 1000);
      }} else {{
        endRecording();
      }}
    }}, 500);
    tryPlayWhenBgReady();
  }} else {{
    startTimer();
  }}
}})();
</script>
</body>
</html>
"""


_SLIDE_FRAGMENT = (
    '<div class="slide" data-start="{start}" data-end="{end}">'
    '<span class="index">{index:02d}</span>'
    '<div class="eyebrow">{eyebrow}</div>'
    '<div class="title">{title}</div>'
    '<div class="narration">{narration}</div>'
    '{broll}'
    '</div>'
)

_BG_VIDEO_FRAGMENT = (
    '<video class="bg-video" src="{url}" autoplay loop muted playsinline '
    'preload="auto"></video>'
)

_WORD_FRAGMENT = (
    '<span class="word" data-start="{start}" data-end="{end}">{text}</span>'
)


def render_lite_html(
    topic: str,
    cues: list[LiteCue],
    output_path: Path,
    *,
    width: int = 720,
    height: int = 1280,
    timestamps: list[dict[str, Any]] | None = None,
    broll_map: dict[str, str] | None = None,
) -> Path:
    """把 JSON cue + ASR 时间戳(含词级)合成 HTML 文件。

    timestamps: [{index, start, end, text, words?}] 秒级; words 缺省时
    旁白渲染为整句(无卡拉OK), 时间轴仍按句级驱动。
    broll_map: {cue_index: 视频URL} —— 每张卡片底层注入循环播放的动态背景;
    缺失/为空则该卡纯色背景(降级)。
    """
    slides = []
    total_ms = 0
    for cue in cues:
        props = cue.props or {}
        eyebrow = str(props.get("eyebrow") or "HEVI · LITE")
        title = str(props.get("title") or f"{topic} · 第 {cue.index + 1} 段")
        span = _span_for(cue, timestamps)
        words = _words_for(cue, timestamps)
        narration_html = _narration_html(cue.narration, span, words)
        broll_html = _broll_html(broll_map, cue.index)
        total_ms = max(total_ms, int(span["end"] * 1000))
        slides.append(
            _SLIDE_FRAGMENT.format(
                index=cue.index,
                eyebrow=html.escape(eyebrow),
                title=html.escape(title),
                narration=narration_html,
                broll=broll_html,
                start=round(span["start"], 3),
                end=round(span["end"], 3),
            )
        )
    if total_ms <= 0:
        total_ms = max(len(cues), 1) * 4000

    full_html = _CARD_TEMPLATE.format(
        width=width,
        height=height,
        slides="\n".join(slides),
        total_ms=total_ms,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_html, encoding="utf-8")
    return output_path


def _broll_html(broll_map: dict[str, str] | None, cue_index: int) -> str:
    """卡片底层动态视频背景; 无 URL 时返回空(纯色底降级)。"""
    url = (broll_map or {}).get(str(cue_index), "").strip()
    if not url:
        return ""
    return _BG_VIDEO_FRAGMENT.format(url=html.escape(url, quote=True))


def _span_for(cue: LiteCue, timestamps: list[dict[str, Any]] | None) -> dict[str, float]:
    if timestamps:
        for row in timestamps:
            if row.get("index") == cue.index:
                return {"start": float(row["start"]), "end": float(row["end"])}
    return {"start": float(cue.index), "end": float(cue.index + 1)}


def _words_for(cue: LiteCue, timestamps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if timestamps:
        for row in timestamps:
            if row.get("index") == cue.index and row.get("words"):
                return [w for w in row["words"] if str(w.get("text", "")).strip()]
    return []


def _narration_html(
    narration: str, span: dict[str, float], words: list[dict[str, Any]]
) -> str:
    """旁白 DOM: 有词级时间戳 → 拆词级卡拉OK span; 否则整句输出(转义)。"""
    if not words:
        return html.escape(narration)
    fragments: list[str] = []
    prev = ""
    for word in words:
        text = str(word.get("text", "")).strip()
        if not text:
            continue
        fragments.append(
            _WORD_FRAGMENT.format(
                start=round(float(word["start"]), 3),
                end=round(float(word["end"]), 3),
                text=html.escape(text),
            )
        )
        # 中文词间不加空格; 拉丁词间补空格保持可读。
        if _needs_space(prev, text):
            fragments.append(" ")
        prev = text
    return "".join(fragments)


def _needs_space(prev: str, cur: str) -> bool:
    """前词末字符与后词首字符至少一侧非 CJK 时插入空格。"""
    if not prev or not cur:
        return False
    return not (_is_cjk(prev[-1]) and _is_cjk(cur[0]))


def _is_cjk(ch: str) -> bool:
    return bool(ch) and (
        "\u3400" <= ch <= "\u4dbf" or "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f"
    )


__all__ = ["render_lite_html"]
