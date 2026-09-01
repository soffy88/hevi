"""Local product-screenshot compositor.

The compositor is deliberately deterministic and asset-first.  It renders a
real PNG/JPG when a local screenshot is supplied and keeps animation keyframes
as an inspectable project contract for the browser/Remotion layer.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

_PROJECTS: dict[str, ScreenshotProject] = {}
FRAME_PRESETS = ("plain", "browser", "safari", "phone", "laptop")
ANNOTATION_KINDS = ("text", "arrow", "rectangle", "circle", "blur")


@dataclass
class ScreenshotLayer:
    layer_id: str
    kind: str  # screenshot | text | arrow | rectangle | circle | blur
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    rotation: float = 0.0
    opacity: float = 1.0
    content: str = ""
    color: str = "#2563eb"
    font_size: int = 32
    blur_radius: int = 12
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenshotProject:
    project_id: str
    title: str
    width: int = 1600
    height: int = 1000
    background: str = "#eef2ff"
    frame: str = "browser"
    layers: list[ScreenshotLayer] = field(default_factory=list)
    keyframes: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["layers"] = [layer.to_dict() for layer in self.layers]
        body["duration_s"] = animation_duration(self)
        return body


def _hex_color(value: str, fallback: str) -> tuple[int, int, int, int]:
    raw = (value or fallback).strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    try:
        rgb = tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))
        return (rgb[0], rgb[1], rgb[2], 255)
    except (ValueError, IndexError):
        return _hex_color(fallback, "#ffffff") if value != fallback else (255, 255, 255, 255)


def _font(size: int) -> Any:
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"):
        path = Path(name)
        if path.exists():
            return ImageFont.truetype(str(path), max(8, size))
    return ImageFont.load_default()


def new_project(
    *,
    title: str = "untitled screenshot",
    screenshot_path: str = "",
    frame: str = "browser",
    width: int = 1600,
    height: int = 1000,
    background: str = "#eef2ff",
) -> ScreenshotProject:
    if frame not in FRAME_PRESETS:
        raise ValueError(f"unknown frame: {frame}")
    project = ScreenshotProject(
        project_id=str(uuid.uuid4()),
        title=title.strip() or "untitled screenshot",
        width=max(320, min(width, 4096)),
        height=max(240, min(height, 4096)),
        background=background,
        frame=frame,
    )
    if screenshot_path:
        project.layers.append(
            ScreenshotLayer(
                layer_id="screen-1",
                kind="screenshot",
                x=180,
                y=120,
                width=project.width - 360,
                height=project.height - 240,
                source=screenshot_path,
            )
        )
    return save_project(project)


def save_project(project: ScreenshotProject) -> ScreenshotProject:
    project.version += 1 if project.project_id in _PROJECTS else 0
    _PROJECTS[project.project_id] = project
    return project


def get_project(project_id: str) -> ScreenshotProject | None:
    return _PROJECTS.get(project_id)


def list_projects() -> list[ScreenshotProject]:
    return list(_PROJECTS.values())


def reset_projects() -> None:
    _PROJECTS.clear()


def update_project(project_id: str, patch: dict[str, Any]) -> ScreenshotProject | None:
    project = get_project(project_id)
    if project is None:
        return None
    for key in ("title", "background", "frame", "keyframes"):
        if key in patch and patch[key] is not None:
            setattr(project, key, patch[key])
    for key in ("width", "height"):
        if key in patch and patch[key] is not None:
            setattr(project, key, max(320 if key == "width" else 240, min(int(patch[key]), 4096)))
    if "layers" in patch:
        project.layers = [_layer_from_dict(item) for item in patch["layers"] if isinstance(item, dict)]
    return save_project(project)


def _layer_from_dict(raw: dict[str, Any]) -> ScreenshotLayer:
    allowed = set(ScreenshotLayer.__dataclass_fields__)
    values = {key: raw[key] for key in allowed if key in raw}
    values.setdefault("layer_id", f"layer-{uuid.uuid4().hex[:8]}")
    values.setdefault("kind", "screenshot")
    return ScreenshotLayer(**values)


def animation_duration(project: ScreenshotProject) -> float:
    ends = [float(item.get("time_s") or 0.0) for item in project.keyframes if isinstance(item, dict)]
    return round(max(ends, default=0.0), 3)


def animation_plan(project: ScreenshotProject) -> dict[str, Any]:
    errors: list[str] = []
    previous = -1.0
    for index, item in enumerate(project.keyframes):
        if not isinstance(item, dict):
            errors.append(f"keyframes[{index}] 必须是对象")
            continue
        time_s = float(item.get("time_s") or 0.0)
        if time_s < previous:
            errors.append(f"keyframes[{index}] 时间必须递增")
        previous = time_s
        if not item.get("layer_id"):
            errors.append(f"keyframes[{index}].layer_id 不能为空")
    return {
        "valid": not errors,
        "duration_s": animation_duration(project),
        "keyframes": project.keyframes,
        "errors": errors,
        "render_note": "静态 PNG/JPG 可由本地合成器直接导出；MP4/WebM/GIF 由前端/Remotion 按此关键帧契约渲染。",
    }


def _paste_transformed(canvas: Image.Image, source: Image.Image, layer: ScreenshotLayer) -> None:
    target_w = layer.width or source.width
    target_h = layer.height or source.height
    image = ImageOps.contain(source.convert("RGBA"), (max(1, target_w), max(1, target_h)))
    if layer.rotation:
        image = image.rotate(layer.rotation, expand=True, resample=Image.Resampling.BICUBIC)
    if layer.opacity < 1:
        image.putalpha(image.getchannel("A").point(lambda value: int(value * max(0.0, min(1.0, layer.opacity)))))
    canvas.alpha_composite(image, (layer.x, layer.y))


def _draw_frame(draw: ImageDraw.ImageDraw, layer: ScreenshotLayer, frame: str) -> None:
    x, y = layer.x, layer.y
    w, h = layer.width or 640, layer.height or 480
    radius = 26 if frame in {"phone", "laptop"} else 14
    if frame == "phone":
        draw.rounded_rectangle((x - 18, y - 42, x + w + 18, y + h + 18), radius=radius, fill="#111827")
        draw.rounded_rectangle((x + w // 2 - 54, y - 34, x + w // 2 + 54, y - 22), radius=6, fill="#374151")
    elif frame in {"browser", "safari"}:
        draw.rounded_rectangle((x - 12, y - 52, x + w + 12, y + h + 12), radius=radius, fill="#ffffff", outline="#cbd5e1", width=2)
        draw.rectangle((x - 10, y - 50, x + w + 10, y - 12), fill="#f8fafc")
        for dot, color in enumerate(("#fb7185", "#fbbf24", "#34d399")):
            draw.ellipse((x + 8 + dot * 18, y - 39, x + 20 + dot * 18, y - 27), fill=color)
    elif frame == "laptop":
        draw.rounded_rectangle((x - 14, y - 14, x + w + 14, y + h + 14), radius=12, fill="#1f2937")
        draw.polygon([(x - 55, y + h + 24), (x + w + 55, y + h + 24), (x + w + 20, y + h + 42), (x - 20, y + h + 42)], fill="#94a3b8")


def render_project(project: ScreenshotProject, output_path: Path) -> dict[str, Any]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (project.width, project.height), _hex_color(project.background, "#eef2ff"))
    draw = ImageDraw.Draw(canvas)
    missing: list[str] = []
    for layer in project.layers:
        if layer.kind == "screenshot":
            source = Path(layer.source)
            if not source.exists():
                missing.append(layer.source)
                continue
            with Image.open(source) as image:
                _draw_frame(draw, layer, project.frame)
                _paste_transformed(canvas, image, layer)
        elif layer.kind == "text":
            draw.text((layer.x, layer.y), layer.content, fill=_hex_color(layer.color, "#2563eb"), font=_font(layer.font_size))
        elif layer.kind in {"rectangle", "circle"}:
            box = (layer.x, layer.y, layer.x + layer.width, layer.y + layer.height)
            if layer.kind == "circle":
                draw.ellipse(box, outline=_hex_color(layer.color, "#2563eb"), width=max(1, layer.font_size // 8))
            else:
                draw.rounded_rectangle(box, radius=8, outline=_hex_color(layer.color, "#2563eb"), width=max(1, layer.font_size // 8))
        elif layer.kind == "arrow":
            end_x = layer.x + layer.width
            end_y = layer.y + layer.height
            draw.line((layer.x, layer.y, end_x, end_y), fill=_hex_color(layer.color, "#2563eb"), width=max(2, layer.font_size // 8))
            draw.polygon([(end_x, end_y), (end_x - 18, end_y - 4), (end_x - 4, end_y - 18)], fill=_hex_color(layer.color, "#2563eb"))
        elif layer.kind == "blur":
            crop_box = (layer.x, layer.y, layer.x + layer.width, layer.y + layer.height)
            crop = canvas.crop(crop_box).filter(ImageFilter.GaussianBlur(max(1, layer.blur_radius)))
            canvas.alpha_composite(crop, (layer.x, layer.y))
    fmt = output_path.suffix.lower()
    if fmt in {".jpg", ".jpeg"}:
        canvas.convert("RGB").save(output_path, quality=94)
    else:
        canvas.save(output_path)
    return {
        "project_id": project.project_id,
        "output_path": str(output_path),
        "format": "jpg" if fmt in {".jpg", ".jpeg"} else "png",
        "width": project.width,
        "height": project.height,
        "missing_sources": missing,
        "animation": animation_plan(project),
    }


__all__ = [
    "ANNOTATION_KINDS",
    "FRAME_PRESETS",
    "ScreenshotLayer",
    "ScreenshotProject",
    "animation_plan",
    "get_project",
    "list_projects",
    "new_project",
    "render_project",
    "reset_projects",
    "update_project",
]
