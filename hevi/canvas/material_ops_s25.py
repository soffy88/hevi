"""S25：画布素材加工（裁切 / 宫格拆分 / 标注 / 局部重绘边界）。

* 裁切、宫格拆分、标注是**纯本地、零成本**的确定性操作，直接做；
* 局部重绘需要生成模型/GPU，本机没有可用推理栈时**不假装能做**，
  ``available=False`` 并给出原因（前端显示“即将开放”）；
* 输出统一写到 ``output/canvas_s25/materials/<batch>/``，不覆盖原素材。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

OUT_ROOT = Path("output/canvas_s25/materials")
MAX_PIXELS = 60_000_000


class MaterialOpError(ValueError):
    pass


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _open(src: Path) -> Image.Image:
    if not src.is_file():
        raise MaterialOpError(f"素材不存在：{src}")
    image = Image.open(src)
    if image.width * image.height > MAX_PIXELS:
        raise MaterialOpError("图片像素过大，拒绝处理")
    return image.convert("RGBA")


def _out_path(batch: str, name: str) -> Path:
    folder = OUT_ROOT / batch
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def new_batch() -> str:
    return uuid.uuid4().hex[:12]


def crop(src: str | Path, box: dict[str, Any], *, out_dir: str | Path | None = None) -> dict[str, Any]:
    """``box`` 用像素 ``{x,y,w,h}``；越界自动裁到图内。"""
    src_path = Path(src)
    image = _open(src_path)
    x = max(0, int(box.get("x") or 0))
    y = max(0, int(box.get("y") or 0))
    w = max(1, int(box.get("w") or image.width))
    h = max(1, int(box.get("h") or image.height))
    x2, y2 = min(image.width, x + w), min(image.height, y + h)
    if x2 <= x or y2 <= y:
        raise MaterialOpError("裁切框在图片外")
    cropped = image.crop((x, y, x2, y2))
    dst = Path(out_dir) / f"{src_path.stem}-crop-{x}-{y}-{x2 - x}x{y2 - y}.png" if out_dir else _out_path(
        new_batch(), f"{src_path.stem}-crop.png"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dst)
    return {"op": "crop", "path": str(dst), "width": cropped.width, "height": cropped.height, "box": [x, y, x2, y2]}


def split_grid(
    src: str | Path,
    *,
    cols: int = 3,
    rows: int = 3,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """按行列均分（宫格）。返回每个子图路径，顺序为从左到右、从上到下。"""
    if cols < 1 or rows < 1 or cols * rows > 100:
        raise MaterialOpError("宫格行列数不合法（1–10 行/列，最多 100 格）")
    src_path = Path(src)
    image = _open(src_path)
    batch = new_batch()
    out: list[dict[str, Any]] = []
    cw, ch = image.width / cols, image.height / rows
    for r in range(rows):
        for c in range(cols):
            left, top = round(c * cw), round(r * ch)
            right, bottom = round((c + 1) * cw), round((r + 1) * ch)
            tile = image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
            dst = (
                Path(out_dir) / f"{src_path.stem}-r{r + 1}c{c + 1}.png"
                if out_dir
                else _out_path(batch, f"{src_path.stem}-r{r + 1}c{c + 1}.png")
            )
            dst.parent.mkdir(parents=True, exist_ok=True)
            tile.save(dst)
            out.append(
                {"row": r, "col": c, "path": str(dst), "width": tile.width, "height": tile.height}
            )
    return {"op": "split_grid", "cols": cols, "rows": rows, "tiles": out, "count": len(out)}


def annotate(
    src: str | Path,
    marks: list[dict[str, Any]],
    *,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """在图上画框 / 箭头 / 文字。``marks`` 元素：``{type,x,y,x2,y2,text,color,width}``。"""
    src_path = Path(src)
    image = _open(src_path).copy()
    draw = ImageDraw.Draw(image)
    applied = 0
    for mark in marks:
        kind = str(mark.get("type") or "box")
        color = str(mark.get("color") or "#ff3b30")
        width = max(1, int(mark.get("width") or max(2, image.width // 300)))
        x, y = int(mark.get("x") or 0), int(mark.get("y") or 0)
        if kind in ("box", "arrow"):
            x2 = int(mark.get("x2", x + max(8, image.width // 6)))
            y2 = int(mark.get("y2", y + max(8, image.height // 6)))
            draw.rectangle([x, y, x2, y2], outline=color, width=width)
            if kind == "arrow":
                draw.line([x, y, x2, y2], fill=color, width=width)
                draw.ellipse([x2 - width * 3, y2 - width * 3, x2 + width * 3, y2 + width * 3], fill=color)
            applied += 1
        elif kind == "text":
            text = str(mark.get("text") or "")
            if not text:
                continue
            font = _font(max(12, int(mark.get("size") or max(16, image.width // 40))))
            bbox = draw.textbbox((x, y), text, font=font)
            draw.rectangle([bbox[0] - 4, bbox[1] - 3, bbox[2] + 4, bbox[3] + 3], fill=color)
            draw.text((x, y), text, fill=str(mark.get("text_color") or "#ffffff"), font=font)
            applied += 1
    if not applied:
        raise MaterialOpError("没有可执行的标注（type 只支持 box/arrow/text）")
    dst = (
        Path(out_dir) / f"{src_path.stem}-annotated.png"
        if out_dir
        else _out_path(new_batch(), f"{src_path.stem}-annotated.png")
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(dst)
    return {"op": "annotate", "path": str(dst), "marks": applied, "width": image.width, "height": image.height}


def inpaint_availability() -> dict[str, Any]:
    """局部重绘需要生成模型；没有就明说，不排队、不扣费。"""
    model_dir = Path("models/inpaint")
    if model_dir.is_dir() and any(model_dir.iterdir()):
        return {"available": True, "reason": "", "mode": "local_model"}
    return {
        "available": False,
        "reason": "本机没有可用的局部重绘模型/GPU 推理栈；为避免误解与扣费，暂不开放。",
        "mode": "coming_soon",
    }


def capabilities() -> dict[str, Any]:
    return {
        "crop": {"available": True, "cost": "free", "note": "像素框裁切，保留原图"},
        "split_grid": {"available": True, "cost": "free", "note": "4/9/16/25 预设或自定义行列"},
        "annotate": {"available": True, "cost": "free", "note": "框 / 箭头 / 文字，颜色可选"},
        "inpaint": inpaint_availability(),
    }
