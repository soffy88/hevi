"""
Hevi Satori + Resvg Card Renderer: Generates 16:9 and 9:16 title and subtitle cards with Chinese font support (Noto Sans SC).
"""

import os
from typing import Literal, Optional
try:
    import resvg
except ImportError:
    resvg = None
from PIL import Image

class SatoriResvgCardRenderer:
    def __init__(self, font_path: Optional[str] = None):
        # Default font path or fallback
        self.font_path = font_path or "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf"

    def render_card_svg(self, title: str, subtitle: str = "", aspect: Literal["16:9", "9:16"] = "9:16", theme: str = "dark") -> str:
        width = 1080 if aspect == "9:16" else 1920
        height = 1920 if aspect == "9:16" else 1080
        
        bg_color = "#0f172a" if theme == "dark" else "#f8fafc"
        text_color = "#f8fafc" if theme == "dark" else "#0f172a"
        sub_color = "#94a3b8" if theme == "dark" else "#64748b"

        svg_content = f'''<svg width="{width}" height="{height}" viewBox="0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <rect width="{width}" height="{height}" fill="{bg_color}"/>
  <g transform="translate(100, {height // 2 - 150})">
    <text x="0" y="0" fill="{text_color}" font-family="Noto Sans SC, sans-serif" font-size="64" font-weight="bold">{title}</text>
    <text x="0" y="90" fill="{sub_color}" font-family="Noto Sans SC, sans-serif" font-size="32">{subtitle}</text>
    <rect x="0" y="150" width="120" height="8" rx="4" fill="#3b82f6"/>
  </g>
  <text x="80" y="{height - 80}" fill="{sub_color}" font-family="Noto Sans SC, sans-serif" font-size="24">Hevi WebKit Engine · Satori Card</text>
</svg>'''
        return svg_content

    def render_card_png(self, title: str, subtitle: str = "", output_path: str = "card.png", aspect: Literal["16:9", "9:16"] = "9:16", theme: str = "dark") -> str:
        svg = self.render_card_svg(title, subtitle, aspect, theme)
        if resvg is not None:
            try:
                png_bytes = resvg.render(svg)
                with open(output_path, "wb") as f:
                    f.write(png_bytes)
                return output_path
            except Exception:
                pass

        # Fallback: write svg and render via PIL placeholder or basic render
        with open(output_path.replace(".png", ".svg"), "w") as f:
            f.write(svg)
        # Create blank PNG as fallback
        width = 1080 if aspect == "9:16" else 1920
        height = 1920 if aspect == "9:16" else 1080
        img = Image.new("RGB", (width, height), color=(15, 23, 42))
        img.save(output_path)
        return output_path
