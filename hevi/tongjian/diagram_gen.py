"""程序生成画面 —— 地图/时间线。见 SPEC-005 §1.4:"地图/世系图/时间线/制度结构图 →
程序生成(确定性,最准),零成本"。

零 LLM、零图像模型——纯 Pillow 确定性绘制。函数签名对齐 obase ImageGenCaller 协议
(`prompt`/`output_path`/`seed`/`extra`,同 hevi/image/sdxl_local_service.py::sdxl_local_generate
的调用形状),直接可当 scene_render.py 的 `image_gen` 参数用。

第一版只覆盖 EventUnit 需要的最小集:简单时间线(标题 + 年代标注)+ 简单地图占位(标题 +
方位文字),不做精细地理绘制——那需要真实地图数据,不是这一批的范围。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

_WIDTH, _HEIGHT = 1024, 576
_BG_COLOR = (24, 22, 18)
_LINE_COLOR = (200, 180, 140)
_TEXT_COLOR = (230, 220, 200)
_MUTED_TEXT_COLOR = (150, 140, 120)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw, y: int, text: str, fill: tuple[int, int, int]
) -> None:
    bbox = draw.textbbox((0, 0), text)
    x = (_WIDTH - (bbox[2] - bbox[0])) / 2
    draw.text((x, y), text, fill=fill)


async def render_timeline_diagram(
    *,
    prompt: str,
    output_path: Path | str,
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """简单时间线:一条横轴 + 事件单元的年代标注点。"""
    extra = extra or {}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (_WIDTH, _HEIGHT), _BG_COLOR)
    draw = ImageDraw.Draw(img)

    title = str(extra.get("title") or prompt)[:40]
    era = str(extra.get("era") or "")
    year = extra.get("year")

    axis_y = _HEIGHT // 2
    draw.line([(120, axis_y), (_WIDTH - 120, axis_y)], fill=_LINE_COLOR, width=2)
    point_x = _WIDTH // 2
    draw.ellipse([point_x - 6, axis_y - 6, point_x + 6, axis_y + 6], fill=_LINE_COLOR)

    _draw_centered_text(draw, axis_y - 60, title, _TEXT_COLOR)
    label = era if year is None else f"{era}  公元{year}年" if era else f"公元{year}年"
    if label:
        _draw_centered_text(draw, axis_y + 20, label, _MUTED_TEXT_COLOR)

    img.save(output_path)
    return {"output_path": str(output_path), "seed": seed or 0}


async def render_map_diagram(
    *,
    prompt: str,
    output_path: Path | str,
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """简单地图占位:标题 + 方位文字,不做精细地理绘制(§1.4 明确的第一版范围)。"""
    extra = extra or {}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (_WIDTH, _HEIGHT), _BG_COLOR)
    draw = ImageDraw.Draw(img)

    title = str(extra.get("title") or prompt)[:40]
    era = str(extra.get("era") or "")

    margin = 60
    draw.rectangle(
        [margin, margin, _WIDTH - margin, _HEIGHT - margin], outline=_LINE_COLOR, width=2
    )
    for label, pos in (
        ("北", (_WIDTH // 2, margin + 20)),
        ("南", (_WIDTH // 2, _HEIGHT - margin - 30)),
        ("西", (margin + 20, _HEIGHT // 2)),
        ("东", (_WIDTH - margin - 30, _HEIGHT // 2)),
    ):
        draw.text(pos, label, fill=_MUTED_TEXT_COLOR)

    _draw_centered_text(draw, _HEIGHT // 2 - 20, title, _TEXT_COLOR)
    if era:
        _draw_centered_text(draw, _HEIGHT // 2 + 20, era, _MUTED_TEXT_COLOR)

    img.save(output_path)
    return {"output_path": str(output_path), "seed": seed or 0}
