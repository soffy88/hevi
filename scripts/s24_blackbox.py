"""S24：六项能力各跑 2 个新主题的黑盒验证。

输出 12 条真实 1080×1920 竖屏 MP4（本地、零付费），并用 S16 五维机械分
（spec / audio / motion / clarity / text）打分；同时记录每项真实产物：
review.json + 审片总览图、word_sync.json、卡片/公众号/长图、article 账本、
翻译校验、AIGC 标识与字体许可。

用法：
    python scripts/s24_blackbox.py --out DIR [--only review,word_sync]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

W, H, FPS = 1080, 1920, 24
DURATION = 12.0
S23_BASELINE = 5.0
CONTAINER = os.environ.get("HEVI_S24_WHISPER_CONTAINER", "hevi-cftunnel-hevi-api-1")
OUTPUT_ROOT = Path(os.environ.get("HEVI_S24_OUTPUT_ROOT", "/home/soffy/projects/hevi/output"))
AIGC_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

THEMES: dict[str, list[str]] = {
    "review": ["手机为什么越充越烫", "为什么超市的牛奶总放在最里面"],
    "word_sync": ["全球人口 80 亿怎么分布", "一杯咖啡从种子到杯子走了多远"],
    "multi_export": ["把一篇长文拆成一张卡片", "为什么你的笔记从来不会再看"],
    "article": ["一条河怎么养活一座城", "为什么老小区的树比新小区多"],
    "localize": ["Why does bread rise twice?", "How does a city cool itself?"],
    "compliance": ["AI 配音的 15 秒科普", "一条带 AIGC 标识的竖屏短片"],
}

NARRATION: dict[str, list[str]] = {
    "手机为什么越充越烫": ["手机越充越烫。", "能量没有消失。", "它变成了热。", "快充时热量更集中。"],
    "为什么超市的牛奶总放在最里面": ["牛奶总在最里面。", "因为它是高频商品。", "让你穿过整家店。", "顺手多买几样。"],
    "全球人口 80 亿怎么分布": ["八十亿人住在哪里？", "大部分人其实住在亚洲。", "真正密集的地方只有几块。", "这就是人口地图。"],
    "一杯咖啡从种子到杯子走了多远": ["一杯咖啡走多远？", "从赤道附近的山坡开始。", "采摘、烘焙、研磨。", "最后才到你的杯子。"],
    "把一篇长文拆成一张卡片": ["长文不必一次读完。", "先抽出一个结论。", "再留三条证据。", "最后做成一页卡片。"],
    "为什么你的笔记从来不会再看": ["笔记不会再看，", "因为你在抄，不在想。", "写给未来的自己。", "只留能用的那一句。"],
    "一条河怎么养活一座城": ["一条河养活一座城。", "先有水，再有路。", "有路才有人。", "人多了才有城。"],
    "为什么老小区的树比新小区多": ["老小区的树更高。", "因为它们先长了几十年。", "新小区先铺路。", "树只能后来补。"],
    "Why does bread rise twice?": ["面包要发酵两次，", "第一次让面团长大，", "第二次让气味出现，", "最后才进烤箱。"],
    "How does a city cool itself?": ["城市靠三件事降温。", "树荫、水面和通风。", "少一点水泥，", "就多一点凉快。"],
    "AI 配音的 15 秒科普": ["这是一段 AI 配音。", "十五秒讲清一件事。", "首帧已经标明 AIGC。", "元数据也写进去了。"],
    "一条带 AIGC 标识的竖屏短片": ["这条短片带标识。", "首帧可见 AI 生成。", "文件元数据同样记录。", "导出时自动写入。"],
}

EN_SOURCE: dict[str, list[str]] = {
    "Why does bread rise twice?": [
        "Bread rises twice: 2 ferments, 1 bake.",
        "The first rise builds 80% of the volume.",
        "The second rise adds flavor in 45 minutes.",
    ],
    "How does a city cool itself?": [
        "A city cools itself with 3 tools: shade, water, airflow.",
        "Trees can cut surface heat by 12 degrees.",
        "Every 10% more concrete adds about 2 degrees.",
    ],
}
ZH_TARGET: dict[str, list[str]] = {
    "Why does bread rise twice?": [
        "面包要发酵两次：2 次发酵，1 次烘烤。",
        "第一次发酵撑起 80% 的体积。",
        "第二次发酵用 45 分钟补上风味。",
    ],
    "How does a city cool itself?": [
        "城市用 3 件工具降温：树荫、水面、通风。",
        "树能把地表温度压低 12 度。",
        "水泥每多 10%，温度大约多 2 度。",
    ],
}


def _run(cmd: list[str], *, timeout: int = 900, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, input=input_text)


def _ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg missing")
    return ff


def _slug(text: str) -> str:
    return f"{abs(hash(text)) % 10000:04d}"


def _piper(text: str, out_wav: Path) -> Path:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    tmp_dir = OUTPUT_ROOT / ".s24_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / f"tts-{_slug(text)}-{time.time_ns()}.wav"
    proc = _run(
        ["docker", "exec", "-i", CONTAINER, "piper",
         "-m", "/opt/piper/voices/zh_CN-huayan-medium.onnx", "-f", f"/app/output/.s24_tmp/{target.name}"],
        input_text=text,
        timeout=180,
    )
    if proc.returncode != 0 or not target.is_file():
        raise RuntimeError(f"piper failed: {(proc.stderr or proc.stdout)[-300:]}")
    shutil.copy2(target, out_wav)
    target.unlink(missing_ok=True)
    return out_wav


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def _loudnorm(wav: Path, out: Path) -> Path:
    """两遍：先 loudnorm，再按实测 I 值补增益，尽量落在 -14±0.4。"""
    from hevi.studio.repurpose_s24 import measure_loudness

    proc = _run([_ffmpeg(), "-y", "-i", str(wav), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", str(out)])
    if proc.returncode != 0:
        raise RuntimeError(f"loudnorm failed: {proc.stderr[-300:]}")
    for _ in range(2):
        measured = measure_loudness(out)
        if measured.get("status") != "measured":
            break
        delta = -14.0 - float(measured["lufs"])
        if abs(delta) <= 0.2:
            break
        adjust = out.with_name(out.stem + f"_adj{abs(delta):.2f}.wav")
        proc = _run([_ffmpeg(), "-y", "-i", str(out), "-af", f"volume={delta:+.2f}dB", str(adjust)])
        if proc.returncode != 0:
            break
        adjust.replace(out)
    return out


def _pad_wav(wav: Path, out: Path, *, seconds: float = DURATION) -> Path:
    proc = _run([
        _ffmpeg(), "-y", "-i", str(wav), "-af", f"apad,atrim=0:{seconds}", str(out),
    ], timeout=180)
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"pad failed: {proc.stderr[-300:]}")
    return out


def _concat_wavs(wavs: list[Path], out: Path) -> Path:
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{wav}'\n" for wav in wavs), encoding="utf-8")
    proc = _run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
    listing.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"concat failed: {proc.stderr[-300:]}")
    return out


def _narration(texts: list[str], out_dir: Path) -> tuple[Path, list[dict[str, Any]], float]:
    wavs: list[Path] = []
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    for index, text in enumerate(texts):
        wav = _piper(text, out_dir / f"tts_{index}.wav")
        span = _wav_duration(wav)
        cues.append({"start": round(cursor, 3), "end": round(cursor + span, 3), "text": text})
        cursor += span
        wavs.append(wav)
    joined = _concat_wavs(wavs, out_dir / "narration.wav")
    norm = _loudnorm(joined, out_dir / "narration_norm.wav")
    padded = _pad_wav(norm, out_dir / "narration_padded.wav")
    return padded, cues, max(cursor, DURATION)


def _split_subtitle(text: str, limit: int = 13) -> list[str]:
    clean = text.strip()
    if len(clean) <= limit:
        return [clean]
    parts: list[str] = []
    current = ""
    for char in clean:
        if len(current) + 1 > limit:
            parts.append(current)
            current = char
        else:
            current += char
    if current:
        parts.append(current)
    return parts


def _fit_cues(cues: list[dict[str, Any]], limit: int = 13) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cue in cues:
        pieces = _split_subtitle(cue["text"], limit=limit)
        if len(pieces) == 1:
            out.append(cue)
            continue
        span = (cue["end"] - cue["start"]) / len(pieces)
        for index, piece in enumerate(pieces):
            out.append({
                "start": round(cue["start"] + span * index, 3),
                "end": round(cue["start"] + span * (index + 1), 3),
                "text": piece,
            })
    return out


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in paths:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    lines, current = [], ""
    for char in text:
        trial = current + char
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def _theme_palette(name: str) -> dict[str, str]:
    palettes = {
        "review": {"bg": "#1A2433", "fg": "#F3F6FA", "accent": "#2EC4B6", "muted": "#9AA7B8", "panel": "#223044"},
        "word_sync": {"bg": "#1C1B28", "fg": "#EDEBF2", "accent": "#8E7CFF", "muted": "#9A96A8", "panel": "#2A2840"},
        "multi_export": {"bg": "#EEF2E9", "fg": "#1E2A22", "accent": "#3E7C59", "muted": "#68766B", "panel": "#DDE6D8"},
        "article": {"bg": "#F4EFE6", "fg": "#1B1C1E", "accent": "#B23A2E", "muted": "#6E6A63", "panel": "#E9E1D3"},
        "localize": {"bg": "#E8D9C4", "fg": "#2A211B", "accent": "#C24A2C", "muted": "#7D6A5B", "panel": "#D8C4A8"},
        "compliance": {"bg": "#1A2433", "fg": "#F3F6FA", "accent": "#2EC4B6", "muted": "#9AA7B8", "panel": "#223044"},
    }
    return palettes[name]


def _hex(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _draw_background(palette: dict[str, str], *, progress: float, title: str = "", subtitle: str = "", index: int = 0) -> Any:
    from PIL import Image, ImageDraw

    base = _hex(palette["bg"])
    accent = _hex(palette["accent"])
    panel = _hex(palette["panel"])
    mix = min(1.0, max(0.0, progress))
    tint = tuple(int(base[i] * (1 - 0.55 * mix) + accent[i] * 0.55 * mix) for i in range(3))
    img = Image.new("RGB", (W, H), tint)
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, W, 220], fill=panel)
    draw.rectangle([0, H - 18, int(W * (0.05 + 0.9 * progress)), H], fill=accent)
    for step in range(7):
        x = int(((progress + step * 0.11) % 1.0) * (W + 260)) - 130
        draw.rounded_rectangle([x - 44, 280 + step * 190, x + 44, 420 + step * 190], radius=22,
                               fill=(*accent, 26 + step * 8))
    cx = int(W * (0.18 + 0.64 * (0.5 - 0.5 * math.cos(progress * math.pi * 6))))
    cy = int(H * (0.30 + 0.10 * math.sin(progress * math.pi * 6)))
    draw.ellipse([cx - 150, cy - 150, cx + 150, cy + 150], outline=accent, width=14)
    draw.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=accent)
    for ring in range(3):
        radius = 190 + ring * 70
        draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=progress * 360,
                 end=progress * 360 + 140, fill=(*accent, 130), width=8)
    sweep = int(((progress * 1.35) % 1.0) * (W + 260)) - 130
    draw.rectangle([sweep - 40, 0, sweep + 40, H], fill=(255, 255, 255, 36))
    draw.rectangle([sweep - 6, 0, sweep + 6, H], fill=(*accent, 120))
    block = 520
    bx = int((W - block) * min(1.0, (progress * 1.7) % 1.0))
    by = int((H - block) * (0.18 + 0.32 * math.sin(progress * math.pi * 2)))
    draw.rounded_rectangle([bx, by, bx + block, by + block], radius=40, fill=(*panel, 110))
    draw.rounded_rectangle([bx + 30, by + 30, bx + block - 30, by + block - 30], radius=28,
                           outline=(*accent, 170), width=10)
    dot_x = int(W * ((progress * 2.2) % 1.0))
    for dot in range(9):
        yy = 260 + dot * 170
        xx = int((dot_x + dot * 90) % W)
        draw.ellipse([xx - 10, yy - 10, xx + 10, yy + 10], fill=(*accent, 150))
    bar_w = 120
    for bar in range(6):
        height = int(180 + 150 * abs(math.sin(progress * 2.1 + bar)))
        x0 = 90 + bar * 160
        draw.rounded_rectangle([x0, H - 360 - height, x0 + bar_w, H - 360], radius=14,
                               fill=accent if bar % 2 == 0 else panel)
    if title:
        font = _font(54, bold=True)
        for line_index, line in enumerate(_wrap(draw, title, font, W - 180)[:2]):
            draw.text((90, 260 + line_index * 68), line, font=font, fill=_hex(palette["fg"]))
    if subtitle:
        font = _font(46)
        lines = _wrap(draw, subtitle, font, W - 200)[:2]
        y = int(H * 0.78) - (len(lines) - 1) * 30
        for line in lines:
            width = int(draw.textlength(line, font=font))
            draw.rounded_rectangle([(W - width) // 2 - 22, y - 10, (W + width) // 2 + 22, y + 62], radius=10,
                                   fill=(0, 0, 0, 110))
            draw.text(((W - width) // 2, y), line, font=font, fill=(255, 255, 255))
            y += 62
    if index:
        draw.text((W - 120, 40), f"{index:02d}", font=_font(40, bold=True), fill=accent)
    return img


def _encode(frames: Path, out: Path, *, wav: Path) -> Path:
    silent = out.with_name(out.stem + "_silent.mp4")
    proc = _run([
        _ffmpeg(), "-y", "-framerate", str(FPS), "-i", str(frames / "f_%04d.png"),
        "-vf", f"scale={W}:{H}:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(silent),
    ])
    if proc.returncode != 0 or not silent.is_file():
        raise RuntimeError(f"encode failed: {proc.stderr[-400:]}")
    proc = _run([
        _ffmpeg(), "-y", "-i", str(silent), "-i", str(wav),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out),
    ])
    silent.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"mux failed: {proc.stderr[-400:]}")
    return out


def _render_pillow(
    out_dir: Path, out: Path, *, texts: list[str], wav: Path, cues: list[dict[str, Any]],
    palette: dict[str, str], title: str, bilingual: tuple[list[str], list[str]] | None = None,
    index: int = 0,
) -> Path:
    frames = Path(tempfile.mkdtemp(prefix="s24-frames-"))
    duration = _wav_duration(wav)
    total = math.ceil(duration * FPS)
    for frame_index in range(total):
        moment = frame_index / FPS
        cue = next((item for item in cues if item["start"] <= moment < item["end"]), None)
        subtitle = cue["text"] if cue else ""
        top = ""
        if bilingual and cue:
            source_cues, target_cues = bilingual
            for source, target in zip(source_cues, target_cues, strict=False):
                if target["start"] <= moment < target["end"]:
                    top, subtitle = source["text"], target["text"]
                    break
        img = _draw_background(palette, progress=min(1.0, moment / max(duration, 0.1)), title=title,
                               subtitle=subtitle, index=index)
        if top:
            from PIL import ImageDraw

            draw = ImageDraw.Draw(img, "RGBA")
            font = _font(38)
            width = int(draw.textlength(top, font=font))
            y = int(H * 0.60)
            draw.rounded_rectangle([(W - width) // 2 - 18, y - 8, (W + width) // 2 + 18, y + 52], radius=8,
                                   fill=(0, 0, 0, 100))
            draw.text(((W - width) // 2, y), top, font=font, fill=_hex(palette["fg"]))
        img.save(frames / f"f_{frame_index + 1:04d}.png")
    result = _encode(frames, out, wav=wav)
    shutil.rmtree(frames, ignore_errors=True)
    return result


def _score(path: Path) -> dict[str, Any]:
    import importlib.util

    module_path = Path(__file__).with_name("s16_blackbox.py")
    spec = importlib.util.spec_from_file_location("s16_blackbox", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("s16_blackbox.py not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score_video(path)


def _word_align(wav: Path, transcript: str) -> list[dict[str, Any]]:
    from hevi.studio import repurpose_s24

    alignment = repurpose_s24.align_words(wav)
    if alignment.get("status") != "measured":
        return []
    return repurpose_s24.map_words_to_transcript(alignment.get("segments") or [], transcript)

# ---------------------------------------------------------------------------
# 1. review
# ---------------------------------------------------------------------------


def _item_review(theme: str, out: Path) -> tuple[Path, dict[str, Any]]:
    from hevi.studio import repurpose_s24

    texts = NARRATION[theme]
    wav, cues, _duration = _narration(texts, out)
    cues = _fit_cues(cues)
    video = _render_pillow(out, out / "clip.mp4", texts=texts, wav=wav, cues=cues,
                           palette=_theme_palette("review"), title=theme)
    narration = [{"text": item["text"], "start": item["start"], "end": item["end"]} for item in cues]
    review = repurpose_s24.review_delivery(
        video, narration=narration, cues=cues,
        subtitle_plan={"hard_cut": True, "band": {"x0": 0.05, "y0": 0.70, "x1": 0.95, "y1": 0.92}},
    )
    review_path = out / "review.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    overview = repurpose_s24.render_review_overview(review, out / "review-overview.png")
    bad = repurpose_s24.review_delivery(
        video,
        narration=[{"text": "这一句故意写得非常非常长用来触发首句字数和语速的硬指标失败，而且还要继续写下去", "start": 0.0, "end": 4.0}],
        cues=[{"start": 0.0, "end": 0.2, "text": "太短"}, {"start": 0.5, "end": 1.6, "text": "这一条字幕明显超过十三个字需要拆分处理"}],
        subtitle_plan={"hard_cut": False},
        frame_check=False,
    )
    extra = {
        "review_pass": review["pass"],
        "review_counts": review["counts"],
        "review_json": str(review_path),
        "review_overview": str(overview),
        "bad_detected_fail": not bad["pass"],
        "bad_fail_ids": sorted({c["id"] for c in bad["checks"] if c["status"] == "fail"}),
        "retry_nodes": [item["node"] for item in review["retry"]],
        "subtitle_cues": len(cues),
    }
    return video, extra

# ---------------------------------------------------------------------------
# 2. word_sync
# ---------------------------------------------------------------------------


def _item_word_sync(theme: str, out: Path) -> tuple[Path, dict[str, Any]]:
    from hevi.studio import repurpose_s24

    texts = NARRATION[theme]
    wav, cue_segments, duration = _narration(texts, out)
    transcript = "".join(texts)
    words = _word_align(wav, transcript)
    if not words:
        raise RuntimeError("whisper alignment unavailable")
    shots = [
        {"id": "n", "kind": "number_roll", "trigger": "八十亿" if "80" in theme else texts[0][:4],
         "value": "80 亿" if "80" in theme else "1 杯", "label": "核心数字", "title": theme},
        {"id": "l", "kind": "checklist", "title": theme,
         "items": [{"text": "先说结论", "trigger": "大部分人" if "80" in theme else "从赤道"},
                   {"text": "再给证据", "trigger": "真正密集" if "80" in theme else "采摘"}]},
        {"id": "c", "kind": "compare", "title": theme,
         "sides": [{"text": "亚洲", "trigger": "亚洲"}, {"text": "其他", "trigger": "哪里"}]},
        {"id": "q", "kind": "quote", "trigger": "这就是" if "80" in theme else "最后",
         "text": "文字只走 HTML/CSS"},
    ]
    plan = repurpose_s24.word_sync_plan(
        transcript=transcript, words=words, shots=shots, theme="night", out_dir=out,
    )
    frames = Path(tempfile.mkdtemp(prefix="s24-html-"))
    bg_path = out / "background.png"
    _draw_background(_theme_palette("word_sync"), progress=0.35, title="").save(bg_path)
    html = plan["html"].replace("</head>", "<style>.s24-subtitle{transition:none}</style></head>")
    html = html.replace("<body>", "<body style=\"background:#12121A url('background.png') center/cover\">")
    for cue in _fit_cues(cue_segments):
        html = html.replace(
            "</body>",
            f"<div class='s24-subtitle' data-start='{cue['start']}' data-end='{cue['end']}'>{cue['text']}</div></body>",
        )
    html_path = out / "word_sync_preview.html"
    html_path.write_text(html, encoding="utf-8")
    _playwright_frames(html_path, frames, duration)
    video = _encode(frames, out / "clip.mp4", wav=wav)
    shutil.rmtree(frames, ignore_errors=True)
    extra = {
        "alignment_source": "whisper_asr_mapped",
        "words": len(words),
        "appear_at": {shot["id"]: shot.get("appear_at") for shot in plan["shots"]},
        "text_in_image": plan["text_in_image"],
        "overlay": plan["overlay"],
        "html_css_variables": plan["css"][:120],
        "word_sync_json": str(out / "word_sync.json"),
        "image_prompt_has_no_text": all("不生成任何文字" in shot["image_prompt"] for shot in plan["shots"]),
    }
    return video, extra


def _playwright_frames(html_path: Path, frames: Path, duration: float) -> None:
    from playwright.sync_api import sync_playwright

    total = math.ceil(duration * FPS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
        )
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.goto(f"file://{html_path}")
        page.wait_for_timeout(300)
        page.add_script_tag(content=(
            "window.S24={seek:function(t){"
            "document.querySelectorAll('[data-at]').forEach(function(el){"
            "var a=parseFloat(el.getAttribute('data-at'));el.style.opacity=(t>=a)?'1':'0';"
            "if(el.classList.contains('s24-number')&&el.dataset.value){"
            "var d=Math.max(0,Math.min(1,(t-a)/0.8));el.textContent=Math.round(parseFloat(el.dataset.value)*d)+'';}"
            "});"
            "var b1=document.querySelector('.s24-bgfx .b1'),b2=document.querySelector('.s24-bgfx .b2');"
            "if(b1){b1.style.transform='translate('+(Math.sin(t*0.9)*260)+'px,'+(Math.cos(t*0.7)*320)+'px) rotate('+(t*18)+'deg)';}"
            "if(b2){b2.style.transform='translate('+(Math.cos(t*0.8)*300)+'px,'+(Math.sin(t*0.6)*380)+'px) rotate('+(-t*24)+'deg)';}"
            "document.querySelectorAll('.s24-subtitle').forEach(function(el){"
            "var s=parseFloat(el.dataset.start),e=parseFloat(el.dataset.end);"
            "el.style.opacity=(t>=s&&t<e)?'1':'0';});}};"
        ))
        for index in range(total):
            page.evaluate(f"window.S24.seek({index / FPS})")
            page.screenshot(path=str(frames / f"f_{index + 1:04d}.png"))
        browser.close()

# ---------------------------------------------------------------------------
# 3. multi_export
# ---------------------------------------------------------------------------


def _item_multi_export(theme: str, out: Path) -> tuple[Path, dict[str, Any]]:
    from hevi.studio import repurpose_s24

    sections = [{"heading": text[:10], "body": text, "bullets": [text, "一稿多发"]}
                for text in NARRATION[theme]]
    manifest = repurpose_s24.export_text_pack(
        title=theme, sections=sections, out_dir=out / "pack", theme="moss", author="S24 黑盒",
    )
    wechat_text = Path(manifest["paths"]["wechat_html"]).read_text(encoding="utf-8")
    wav, cues, _duration = _narration(NARRATION[theme], out)
    cues = _fit_cues(cues)
    video = _render_pillow(out, out / "clip.mp4", texts=NARRATION[theme], wav=wav, cues=cues,
                           palette=_theme_palette("multi_export"), title=theme)
    from PIL import Image

    cards = [Path(path) for path in manifest["paths"]["cards"]]
    sizes = [Image.open(path).size for path in cards]
    extra = {
        "cards": len(cards),
        "card_sizes": sizes,
        "wechat_base64_images": manifest["wechat_images_base64"],
        "wechat_external_refs": manifest["wechat_external_refs"],
        "wechat_has_copy_button": "复制到公众号" in wechat_text,
        "long_image": manifest["paths"]["long_image"],
        "caption": Path(manifest["paths"]["caption"]).read_text(encoding="utf-8").splitlines()[:2],
        "theme_css": Path(manifest["paths"]["theme_css"]).read_text(encoding="utf-8")[:90],
        "subtitle_style": manifest["subtitle_style"],
    }
    return video, extra

# ---------------------------------------------------------------------------
# 4. article
# ---------------------------------------------------------------------------


ARTICLE_TEXT = {
    "一条河怎么养活一座城": "# 一条河怎么养活一座城\n\n先有水，再有路。河流把人和货物带到一起。\n\n有路才有人，人多了才有城。\n\n城市沿河生长，也沿河改道。\n",
    "为什么老小区的树比新小区多": "# 为什么老小区的树比新小区多\n\n老小区的树先长了几十年。\n\n新小区先铺路，树只能后来补。\n\n树荫不是装饰，是时间留下的基础设施。\n",
}


def _item_article(theme: str, out: Path) -> tuple[Path, dict[str, Any]]:
    from hevi.studio import repurpose_s24

    source = out / "source.md"
    source.write_text(ARTICLE_TEXT[theme], encoding="utf-8")
    result = repurpose_s24.ingest_article(str(source), out / "article", author="S24 黑盒")
    ledger = json.loads(Path(result["ledger"]["path"]).read_text(encoding="utf-8"))
    blocks = ledger["blocks"]
    pack = repurpose_s24.export_text_pack(
        title=theme,
        sections=[{"heading": block["text"][:10], "body": block["text"]} for block in blocks if block["kind"] == "paragraph"],
        out_dir=out / "pack",
        theme="editorial",
        author="S24 黑盒",
        source_blocks=blocks,
    )
    verify = pack["ledger_check"]
    wav, cues, _duration = _narration(NARRATION[theme], out)
    cues = _fit_cues(cues)
    video = _render_pillow(out, out / "clip.mp4", texts=NARRATION[theme], wav=wav, cues=cues,
                           palette=_theme_palette("article"), title=theme)
    guard = repurpose_s24.guard_video_transcript(
        url="https://example.com/owned-video", rights_basis="self", author="S24 黑盒",
    )
    extra = {
        "block_count": len(blocks),
        "block_kinds": [block["kind"] for block in blocks],
        "ledger_sha256": [block["sha256"][:12] for block in blocks],
        "readback_ok": verify["ok"],
        "readback_mode": verify["mode"],
        "article_md": result["article_md"],
        "article_chars": result["chars"],
        "video_rights": guard["rights_basis"],
        "no_bulk_no_cookies": guard["bulk"] is False and guard["cookie_use"] is False,
    }
    return video, extra

# ---------------------------------------------------------------------------
# 5. localize
# ---------------------------------------------------------------------------


def _item_localize(theme: str, out: Path) -> tuple[Path, dict[str, Any]]:
    from hevi.studio import repurpose_s24

    source_blocks = EN_SOURCE[theme]
    target_blocks = ZH_TARGET[theme]
    check = repurpose_s24.check_localization(source_blocks, target_blocks, source_lang="en", target_lang="zh")
    negative = repurpose_s24.check_localization(
        source_blocks, [target_blocks[0], "这一段把数字拿掉了", target_blocks[2]],
    )
    wav, cues, _duration = _narration(NARRATION[theme], out)
    cues = _fit_cues(cues)
    display_title = {"Why does bread rise twice?": "面包为什么要发酵两次",
                     "How does a city cool itself?": "城市怎么给自己降温"}.get(theme, theme)
    video = _render_pillow(out, out / "clip.mp4", texts=NARRATION[theme], wav=wav, cues=cues,
                           palette=_theme_palette("localize"), title=display_title)
    extra = {
        "localization_ok": check["ok"],
        "block_count": check["block_count"],
        "number_loss": check["number_loss"],
        "negative_detected": not negative["ok"],
        "negative_number_loss": negative["number_loss"],
        "merged_into": "localization_dub",
    }
    return video, extra

# ---------------------------------------------------------------------------
# 6. compliance
# ---------------------------------------------------------------------------


def _item_compliance(theme: str, out: Path) -> tuple[Path, dict[str, Any]]:
    from hevi.studio import repurpose_s24

    wav, cues, _duration = _narration(NARRATION[theme], out)
    cues = _fit_cues(cues)
    base = _render_pillow(out, out / "base.mp4", texts=NARRATION[theme], wav=wav, cues=cues,
                          palette=_theme_palette("compliance"), title=theme)
    stamped = out / "clip.mp4"
    manifest = repurpose_s24.stamp_aigc(base, stamped, label="AI生成")
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    _run([_ffmpeg(), "-y", "-ss", "0.4", "-i", str(stamped), "-frames:v", "1", str(frames / "first.png")])
    _run([_ffmpeg(), "-y", "-ss", "4.0", "-i", str(stamped), "-frames:v", "1", str(frames / "later.png")])
    from PIL import Image

    def white_ratio(path: Path) -> float:
        img = Image.open(path).convert("L").crop((20, 20, 420, 130))
        import numpy as np

        arr = np.asarray(img, dtype="uint8")
        return round(float((arr >= 200).mean()), 5)

    voice_pack = repurpose_s24.check_voice_tier("huayan", cloned=False)
    voice_clone = repurpose_s24.check_voice_tier("self-voice", cloned=True, rights_basis="self", confirmed=True)
    voice_blocked = None
    try:
        repurpose_s24.check_voice_tier("other", cloned=True, rights_basis="other")
    except ValueError as exc:
        voice_blocked = str(exc)
    fonts = repurpose_s24.font_licenses(root=Path(__file__).resolve().parent.parent)
    extra = {
        "aigc_label": manifest["label"],
        "metadata_comment": manifest["metadata_written"]["comment"],
        "first_frame_white_ratio": white_ratio(frames / "first.png"),
        "later_frame_white_ratio": white_ratio(frames / "later.png"),
        "first_frame_marked": white_ratio(frames / "first.png") > white_ratio(frames / "later.png"),
        "voice_pack_ok": voice_pack["ok"],
        "voice_clone_confirmed": voice_clone["ok"],
        "voice_clone_blocked": voice_blocked,
        "fonts_allowed": fonts["allowed"],
        "fonts_blocked": fonts["blocked"],
        "manifest": str(stamped.with_suffix(".aigc.json")),
    }
    return stamped, extra

# ---------------------------------------------------------------------------
# 调度 / 汇总
# ---------------------------------------------------------------------------

RUNNERS = {
    "review": _item_review,
    "word_sync": _item_word_sync,
    "multi_export": _item_multi_export,
    "article": _item_article,
    "localize": _item_localize,
    "compliance": _item_compliance,
}


def run_theme(item: str, theme: str, out: Path) -> dict[str, Any]:
    slug = f"{item}_{_slug(theme)}"
    dest = out / item / slug
    dest.mkdir(parents=True, exist_ok=True)
    started = time.time()
    failures: list[str] = []
    for attempt in range(2):
        try:
            video, extra = RUNNERS[item](theme, dest)
            score = _score(video)
            return {
                "item": item, "theme": theme, "status": "completed",
                "video": str(video), "elapsed_s": round(time.time() - started, 1),
                "attempts": attempt + 1, "checks": extra, **score,
            }
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}"[:400])
    return {
        "item": item, "theme": theme, "status": "skipped",
        "error": " | ".join(failures), "elapsed_s": round(time.time() - started, 1),
        "exists": False, "score": 0.0, "pass": False,
    }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_item: dict[str, dict[str, Any]] = {}
    for item in THEMES:
        rows = [row for row in results if row["item"] == item]
        scores = [row["score"] for row in rows if row.get("exists")]
        average = round(sum(scores) / len(scores), 2) if scores else 0.0
        by_item[item] = {
            "themes": len(THEMES[item]),
            "real_files": len(scores),
            "average_score": average,
            "s23_baseline": S23_BASELINE,
            "delta_vs_s23": round(average - S23_BASELINE, 2),
            "all_exist": len(scores) == len(rows) == len(THEMES[item]),
            "pass": len(scores) == len(rows) == len(THEMES[item]) and average >= 4.0,
        }
    scored = [row["average_score"] for row in by_item.values() if row["real_files"]]
    overall = round(sum(scored) / len(scored), 2) if scored else 0.0
    return {
        "items": by_item,
        "overall_average": overall,
        "s23_baseline": S23_BASELINE,
        "delta_vs_s23": round(overall - S23_BASELINE, 2),
        "skipped": [row for row in results if row["status"] != "completed"],
        "pass": all(row["pass"] for row in by_item.values()),
        "note": "S16 五维机械分；S23 基线 5.0；每条仍按 4.0 门槛判定。",
    }


def markdown(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = ["# S24 黑盒：六项 × 2 个新主题", ""]
    lines += ["| 项目 | 真实文件 | 平均分 | S23 基线 | 差值 | 通过 |", "|---|---|---|---|---|---|"]
    for item, row in summary["items"].items():
        lines.append(
            f"| {item} | {row['real_files']}/{row['themes']} | {row['average_score']} | "
            f"{row['s23_baseline']} | {row['delta_vs_s23']:+} | {'是' if row['pass'] else '否'} |"
        )
    lines += ["", f"总平均 **{summary['overall_average']}**，相对 S23 {summary['delta_vs_s23']:+}。", ""]
    lines += ["| 项目 | 主题 | 状态 | 分数 | 耗时 | 文件 |", "|---|---|---|---|---|---|"]
    for row in results:
        lines.append(
            f"| {row['item']} | {row['theme']} | {row['status']} | {row.get('score', 0)} | "
            f"{row.get('elapsed_s', 0)}s | {Path(row.get('video', '')).name} |"
        )
    lines += ["", "## 关键自检数字", ""]
    for row in results:
        if row["status"] != "completed":
            continue
        checks = row.get("checks") or {}
        lines.append(f"### {row['item']} · {row['theme']}")
        for key in (
            "review_pass", "review_counts", "bad_detected_fail", "bad_fail_ids",
            "alignment_source", "words", "appear_at", "text_in_image",
            "cards", "wechat_base64_images", "wechat_external_refs", "wechat_has_copy_button",
            "block_count", "readback_ok", "readback_mode", "video_rights",
            "localization_ok", "number_loss", "negative_detected",
            "metadata_comment", "first_frame_marked", "voice_clone_blocked", "fonts_blocked",
        ):
            if key in checks:
                lines.append(f"- {key}: `{json.dumps(checks[key], ensure_ascii=False)}`")
        lines.append("")
    return "\n".join(lines)


def _bootstrap_env() -> None:
    if os.environ.get("JWT_SECRET"):
        return
    env_file = Path(os.environ.get("HEVI_ENV_FILE", "/data/soffy/projects/hevi-release/.env"))
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            for key, value in dotenv_values(env_file).items():
                if value is not None:
                    os.environ.setdefault(key, value)
        except Exception:
            pass
    os.environ.setdefault("APP_ENV", "development")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    _bootstrap_env()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {part.strip() for part in args.only.split(",") if part.strip()}
    results: list[dict[str, Any]] = []
    for item, themes in THEMES.items():
        if only and item not in only:
            continue
        for theme in themes:
            row = run_theme(item, theme, out)
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = summarise(results)
    (out / "s24_blackbox.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "s24_blackbox.md").write_text(markdown(summary, results), encoding="utf-8")
    sums = []
    for row in results:
        path = Path(row.get("video", ""))
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sums.append(f"{digest}  {path.relative_to(out)}")
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
