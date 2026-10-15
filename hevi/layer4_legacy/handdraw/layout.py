"""Hevi Handdraw Line: Responsive Layout & Typography Engine.

Supports both 1920x1080 (Landscape) and 1080x1920 (Portrait) canvases.
Dynamically calculates bounding boxes, text font sizes, illustration scales,
and subtitle margins to prevent overflow and visual collisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanvasLayout:
    width: int
    height: int
    orientation: str  # "landscape" or "portrait"
    title_x: int
    title_y: int
    title_size: int
    marker_w: int
    marker_h: int
    illu_x: int
    illu_y: int
    illu_w: int
    illu_h: int
    illu_max_w: int
    illu_max_h: int
    note_x: int
    note_y: int
    note_size: int
    caption_font_size: int
    caption_bottom_margin: int
    caption_max_width_ratio: float


def compute_canvas_layout(width: int, height: int) -> CanvasLayout:
    """Returns responsive coordinates and font sizes for the given canvas aspect."""
    if width >= height:
        # Landscape: e.g. 1920x1080
        return CanvasLayout(
            width=width,
            height=height,
            orientation="landscape",
            title_x=round(width * 0.06),
            title_y=round(height * 0.08),
            title_size=round(height * 0.052),  # ~56px at 1080
            marker_w=round(width * 0.28),
            marker_h=22,
            illu_x=round(width * 0.52),
            illu_y=round(height * 0.16),
            illu_w=round(width * 0.42),
            illu_h=round(height * 0.68),
            illu_max_w=round(width * 0.42),
            illu_max_h=round(height * 0.68),
            note_x=round(width * 0.06),
            note_y=round(height * 0.32),
            note_size=round(height * 0.040),  # ~43px at 1080
            caption_font_size=max(56, round(height * 0.052)),  # Preschool captions >=56px
            caption_bottom_margin=round(height * 0.045),  # ~48px
            caption_max_width_ratio=0.76,
        )
    # Portrait: e.g. 1080x1920
    return CanvasLayout(
        width=width,
        height=height,
        orientation="portrait",
        title_x=round(width * 0.08),  # ~86px
        title_y=round(height * 0.06),  # ~115px
        title_size=round(width * 0.050),  # ~54px
        marker_w=round(width * 0.55),
        marker_h=24,
        illu_x=round((width - width * 0.78) / 2),  # centered ~118px
        illu_y=round(height * 0.22),  # ~420px
        illu_w=round(width * 0.78),  # ~840px
        illu_h=round(width * 0.78),  # ~840px (square)
        illu_max_w=round(width * 0.78),
        illu_max_h=round(width * 0.78),
        note_x=round(width * 0.08),
        note_y=round(height * 0.72),  # ~1380px
        note_size=round(width * 0.042),  # ~45px
        caption_font_size=max(60, round(width * 0.056)),  # Portrait captions >=56px
        caption_bottom_margin=round(height * 0.055),  # ~105px
        caption_max_width_ratio=0.86,
    )


def build_page_actions(
    page_index: int,
    beat_id: str,
    title_text: str,
    note_text: str,
    illu_source_rel: str,
    illu_parts: list[dict[str, Any]],
    layout: CanvasLayout,
    *,
    marker_style: str = "highlight",
    accent_circle: bool = False,
) -> list[dict[str, Any]]:
    """Builds the list of drawing actions for one beat under the specified layout."""
    actions = []

    # 1. Title text
    actions.append({
        "type": "text",
        "text": title_text,
        "x": layout.title_x,
        "y": layout.title_y,
        "size": layout.title_size,
        "weight": 1.2,
    })

    # 2. Marker accent under/around title
    actions.append({
        "type": "marker",
        "style": marker_style,
        "x": layout.title_x - 10,
        "y": layout.title_y + layout.title_size + 6,
        "width": layout.marker_w,
        "height": layout.marker_h,
        "weight": 0.4,
    })

    # 3. Main Illustration
    actions.append({
        "type": "illustration",
        "source": illu_source_rel,
        "parts": illu_parts,
        "x": layout.illu_x,
        "y": layout.illu_y,
        "width": layout.illu_w,
        "height": layout.illu_h,
        "weight": 2.5,
    })

    # 4. Optional accent circle or focus box
    if accent_circle:
        actions.append({
            "type": "marker",
            "style": "circle",
            "x": layout.illu_x - 15,
            "y": layout.illu_y - 15,
            "width": layout.illu_w + 30,
            "height": layout.illu_h + 30,
            "weight": 0.5,
        })

    # 5. Explanatory key note text
    if note_text:
        actions.append({
            "type": "text",
            "text": note_text,
            "x": layout.note_x,
            "y": layout.note_y,
            "size": layout.note_size,
            "weight": 1.0,
        })

    return actions
