"""动态信息图:短语编号驱动的累积 PPT,禁止按字数估时。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.explainer.phrase_timeline import infer_relationship, phrases_from_narration

PAPER = (252, 248, 240)
INK = (32, 36, 44)
ACCENT = (166, 44, 44)
MUTED = (90, 96, 108)


def _font(size: int) -> Any:
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def deck_spec_from_narration(text: str, duration_ms: int) -> dict[str, Any]:
    """无 ASR 时仍用短语编号做结构,时间轴只在有 captions 时锁定。

    这里只产出页面结构。正式入场帧必须由 phrase-timeline 的 start_ms 提供;
    缺 captions 时调用方只能把整页当作一条 phrase,不得按字数切开估时。
    """
    phrases = phrases_from_narration(text) or [text.strip() or "要点"]
    title = phrases[0][:24]
    return {
        "page_title": title,
        "core_idea": text.strip()[:80],
        "relationship_type": infer_relationship(text),
        "items": [
            {"id": f"p{i:02d}", "text": phrase}
            for i, phrase in enumerate(phrases[:8], start=1)
        ],
        "duration_ms": int(duration_ms),
    }


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines or [text]


def render_deck_frame(
    spec: dict[str, Any],
    *,
    width: int,
    height: int,
    revealed: int,
) -> Image.Image:
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)
    title_font = _font(max(22, width // 28))
    body_font = _font(max(16, width // 42))
    title = str(spec.get("page_title") or "要点")
    draw.text((width * 0.08, height * 0.08), title, fill=INK, font=title_font)
    items = list(spec.get("items") or [])
    y = int(height * 0.22)
    for index, item in enumerate(items):
        if index >= revealed:
            break
        label = str(item.get("text") or "")
        bullet = f"{index + 1}. {label}"
        for line in _wrap(draw, bullet, body_font, int(width * 0.8)):
            draw.text((width * 0.1, y), line, fill=INK if index == 0 else MUTED, font=body_font)
            y += int(body_font.size * 1.55)
        y += 8
    rel = spec.get("relationship_type") or "none"
    if rel in {"sequence", "cause"} and revealed >= 2:
        draw.line((width * 0.1, y, width * 0.7, y), fill=ACCENT, width=4)
        caption = "步骤" if rel == "sequence" else "因果"
        draw.text((width * 0.72, y - 12), caption, fill=ACCENT, font=body_font)
    return image


def render_infographic_cue(
    text: str,
    *,
    duration_ms: int,
    dest: Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 12,
    timeline: dict[str, Any] | None = None,
) -> Path:
    from hevi.explainer.whiteboard import _encode_mp4

    spec = deck_spec_from_narration(text, duration_ms)
    items = spec["items"]
    phrases = list((timeline or {}).get("phrases") or [])
    total_frames = max(int(duration_ms / 1000 * fps), 2)
    frames: list[Image.Image] = []
    for i in range(total_frames):
        now_ms = int(i / fps * 1000)
        if phrases:
            revealed = 0
            for phrase, _item in zip(phrases, items, strict=False):
                if int(phrase.get("start_ms") or 0) <= now_ms:
                    revealed += 1
            revealed = max(1, revealed)
        else:
            # 无 token 时间戳:整页一次给出,绝不按字数拆毫秒。
            revealed = len(items) or 1
        frames.append(render_deck_frame(spec, width=width, height=height, revealed=revealed))
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _encode_mp4(frames, dest, fps)
