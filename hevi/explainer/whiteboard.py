"""白板手绘:分区遮罩编排 + 网格流式笔迹(cs-board 画法的 Pillow/PyAV 内化)。

不引入 OpenCV。缺插画时用暖米黄纸张底合成一张中文重点卡,再沿网格落墨。
失败不挡装配——调用方降级为 voiceover。
"""

from __future__ import annotations

import contextlib
import logging
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from hevi.explainer.contracts import ExplainerCue

logger = logging.getLogger(__name__)

PAPER = (245, 235, 215)
INK = (40, 36, 32)
ACCENT = (180, 70, 48)


def _font(size: int) -> Any:
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def synthesize_still(text: str, *, width: int = 1280, height: int = 720) -> Image.Image:
    """无参考图时的纸张底重点卡。图片模型不写字,这里本地叠中文。"""
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)
    phrase = (text or "重点").strip().replace("\n", "")[:10] or "重点"
    font = _font(max(28, width // 16))
    bbox = draw.textbbox((0, 0), phrase, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = (width - tw) // 2, (height - th) // 2
    pad = 28
    draw.rounded_rectangle(
        (x - pad, y - pad, x + tw + pad, y + th + pad),
        radius=18,
        outline=INK,
        width=6,
    )
    draw.text((x, y), phrase, fill=INK, font=font)
    # 一条底线当「已画完」锚,网格笔迹有东西可扫。
    draw.line((width * 0.18, height * 0.72, width * 0.82, height * 0.72), fill=ACCENT, width=8)
    return image


def default_annotation(width: int, height: int, duration_ms: int, subtitle: str) -> dict[str, Any]:
    return {
        "sceneId": "scene-01",
        "canvas": {"width": width, "height": height},
        "sceneDurationMs": int(duration_ms),
        "elements": [
            {
                "id": "focus",
                "label": "重点",
                "sequence": 1,
                "narrativeRole": "本幕核心观点",
                "subtitle": subtitle,
                "region": {"x": 0, "y": 0, "width": width, "height": height},
                "reveal": {
                    "startMs": 0,
                    "durationMs": max(int(duration_ms) - 400, 200),
                    "protectedRegions": [],
                },
            }
        ],
    }


def _grid_path(mask: Image.Image, step: int = 12) -> list[tuple[int, int]]:
    pixels = mask.load()
    if pixels is None:
        raise RuntimeError("unable to load whiteboard mask pixels")
    width, height = mask.size
    points: list[tuple[int, int]] = []
    for row_index, y in enumerate(range(0, height, step)):
        row = [(x, y) for x in range(0, width, step) if _mask_is_ink(pixels, x, y)]
        if row_index % 2:
            row.reverse()
        points.extend(row)
    return points


def _mask_is_ink(pixels: Any, x: int, y: int) -> bool:
    value = pixels[x, y]
    return isinstance(value, (int, float)) and value > 0


def _region_mask(
    canvas: tuple[int, int],
    region: dict[str, Any],
    later: list[dict[str, Any]],
    protected: list[dict[str, Any]],
) -> Image.Image:
    mask = Image.new("L", canvas, 0)
    draw = ImageDraw.Draw(mask)
    x, y = int(region["x"]), int(region["y"])
    draw.rectangle((x, y, x + int(region["width"]), y + int(region["height"])), fill=255)
    for other in [*later, *protected]:
        ox, oy = int(other["x"]), int(other["y"])
        draw.rectangle((ox, oy, ox + int(other["width"]), oy + int(other["height"])), fill=0)
    return mask


def _stamp(canvas: Image.Image, source: Image.Image, point: tuple[int, int], radius: int, ink: bool) -> None:
    x, y = point
    box = (max(0, x - radius), max(0, y - radius), min(canvas.size[0], x + radius), min(canvas.size[1], y + radius))
    if box[2] <= box[0] or box[3] <= box[1]:
        return
    patch = source.crop(box)
    if ink:
        patch = patch.convert("L").point(lambda p: int(p * 0.35)).convert("RGB")
    canvas.paste(patch, box)


def _encode_mp4(frames: list[Image.Image], dest: Path, fps: int) -> Path:
    import av

    dest.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(dest), mode="w")
    try:
        stream = container.add_stream("libx264", rate=fps)
    except Exception:
        stream = container.add_stream("mpeg4", rate=fps)
    stream.width = frames[0].size[0]
    stream.height = frames[0].size[1]
    stream.pix_fmt = "yuv420p"
    with contextlib.suppress(Exception):
        stream.options = {"crf": "28", "preset": "ultrafast"}
    for image in frames:
        factory_name = "from_image"
        frame = getattr(av.VideoFrame, factory_name)(image.convert("RGB"))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return dest


def render_stream_whiteboard(
    source: Image.Image,
    annotation: dict[str, Any],
    dest: Path,
    *,
    fps: int = 12,
    brush: int = 18,
) -> Path:
    """共享画布上按 sequence 串行落墨。时长只来自 annotation,不按字数估。"""
    width, height = source.size
    duration_ms = int(annotation.get("sceneDurationMs") or 1000)
    elements = sorted(
        annotation.get("elements") or [],
        key=lambda item: int(item.get("sequence") or 0),
    )
    if not elements:
        elements = default_annotation(width, height, duration_ms, "")["elements"]
    total_frames = max(math.ceil(duration_ms / 1000 * fps), 2)
    canvas = Image.new("RGB", (width, height), PAPER)
    frames: list[Image.Image] = []
    # Pre-compute per-element paths and frame windows.
    windows: list[tuple[int, int, list[tuple[int, int]]]] = []
    for index, element in enumerate(elements):
        reveal = element.get("reveal") or {}
        start_ms = int(reveal.get("startMs") or 0)
        dur_ms = int(reveal.get("durationMs") or max(duration_ms - start_ms, 200))
        start_f = min(total_frames - 1, round(start_ms / 1000 * fps))
        end_f = min(total_frames, max(start_f + 1, round((start_ms + dur_ms) / 1000 * fps)))
        later = [el.get("region") for el in elements[index + 1 :] if el.get("region")]
        protected = list(reveal.get("protectedRegions") or [])
        mask = _region_mask((width, height), element.get("region") or {}, later, protected)
        path = _grid_path(mask) or [(width // 2, height // 2)]
        windows.append((start_f, end_f, path))

    for frame_i in range(total_frames):
        t_canvas = canvas.copy()
        for (start_f, end_f, path), _element in zip(windows, elements, strict=False):
            if frame_i < start_f:
                continue
            span = max(end_f - start_f, 1)
            progress = min(1.0, (frame_i - start_f + 1) / span)
            ink_cut = 2 / 3
            count = max(1, int(len(path) * min(progress / ink_cut, 1.0)))
            ink = progress <= ink_cut
            if progress > ink_cut:
                count = len(path)
            for point in path[:count]:
                _stamp(t_canvas, source, point, brush, ink=ink and progress <= ink_cut)
            if progress > ink_cut:
                color_p = (progress - ink_cut) / (1 - ink_cut)
                color_n = max(1, int(len(path) * color_p))
                for point in path[:color_n]:
                    _stamp(t_canvas, source, point, brush, ink=False)
        if frame_i == total_frames - 1:
            t_canvas = source.copy()
        frames.append(t_canvas)
        canvas = t_canvas
    return _encode_mp4(frames, dest, fps)


def _job_id_for(output_dir: Path) -> str:
    resolved = output_dir.resolve()
    name = resolved.parent.name if resolved.name == "preview" else resolved.name
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name) or "explainer"


def _stage_asset(
    src: Path,
    output_dir: Path,
    index: int,
    remotion_public: Path | None,
    kind: str,
) -> str:
    rel = f"runs/{_job_id_for(output_dir)}/{kind}/cue-{index}.mp4"
    local = output_dir / kind / f"cue-{index}.mp4"
    local.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != local.resolve():
        local.write_bytes(src.read_bytes())
    if remotion_public is not None:
        public = Path(remotion_public) / rel
        public.parent.mkdir(parents=True, exist_ok=True)
        if public.resolve() != local.resolve():
            public.write_bytes(local.read_bytes())
        return rel
    return str(local)


async def attach_whiteboard_scenes(
    cues: list[ExplainerCue],
    output_dir: Path,
    *,
    enabled: bool = True,
    remotion_public: Path | None = None,
    width: int = 1920,
    height: int = 1080,
    fps: int = 12,
) -> list[ExplainerCue]:
    """给 whiteboard / infographic cue 渲 mp4 写 assetUrl。失败降级 voiceover。"""
    if not enabled:
        for cue in cues:
            if cue.visual_type in {"whiteboard", "infographic"}:
                cue.visual_type = "voiceover"
        return cues
    for index, cue in enumerate(cues, start=1):
        if cue.visual_type not in {"whiteboard", "infographic"}:
            continue
        if str((cue.visual_config or {}).get("assetUrl") or "").strip():
            continue
        duration_ms = int(max(float(cue.time_estimate_s or 5.0), 0.5) * 1000)
        cfg = dict(cue.visual_config or {})
        try:
            kind = "infographic" if cue.visual_type == "infographic" else "whiteboard"
            raw = output_dir / kind / f"cue-{index}.raw.mp4"
            if kind == "infographic":
                from hevi.explainer.infographic import render_infographic_cue
                from hevi.explainer.phrase_timeline import build_phrase_timeline

                timeline = cfg.get("phrase_timeline")
                if timeline is None and cfg.get("captions"):
                    timeline = build_phrase_timeline(cue.text, list(cfg["captions"]))
                    cue.visual_config["phrase_timeline"] = timeline

                produced = render_infographic_cue(
                    cue.text,
                    duration_ms=duration_ms,
                    dest=raw,
                    width=width,
                    height=height,
                    fps=fps,
                    timeline=timeline,
                )
            else:
                still = synthesize_still(cue.text, width=width, height=height)
                annotation = cfg.get("annotation") or default_annotation(
                    width, height, duration_ms, cue.text[:40]
                )
                produced = render_stream_whiteboard(still, annotation, raw, fps=fps)
            cue.visual_config["assetUrl"] = _stage_asset(
                produced, output_dir, index, remotion_public, kind
            )
        except Exception:
            logger.exception("whiteboard/infographic cue %s 渲染失败,降级 voiceover", index)
            cue.visual_type = "voiceover"
    return cues
