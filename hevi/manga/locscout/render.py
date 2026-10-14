"""M3 OSM 实景街区 (locscout) — renderer and ODbL attribution.

Renders 3D comic-style street scene and stamps the required ODbL attribution:
"© OpenStreetMap contributors" at the bottom right of every image.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..common import write_json, sha256_file, RenderSize
from ..common.renderer import FrameRenderer, encode_video, make_contact_sheet, ffprobe
from .builder import LocationSpec, build_location_scene
from .template import build_html

OSM_ATTRIBUTION_TEXT = "© OpenStreetMap contributors"


def stamp_osm_attribution(img_path: str | Path) -> None:
    """Stamp '© OpenStreetMap contributors' at the bottom-right corner."""
    p = Path(img_path)
    im = Image.open(p).convert("RGBA")
    draw = ImageDraw.Draw(im)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    # Calculate text bounding box
    bbox = draw.textbbox((0, 0), OSM_ATTRIBUTION_TEXT, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    margin = 12
    box_pad = 6
    bx2 = im.width - margin
    by2 = im.height - margin
    bx1 = bx2 - tw - 2 * box_pad
    by1 = by2 - th - 2 * box_pad

    # Semi-transparent background box for contrast
    draw.rectangle([bx1, by1, bx2, by2], fill=(255, 255, 255, 220), outline=(100, 100, 100, 255), width=1)
    draw.text((bx1 + box_pad, by1 + box_pad - 1), OSM_ATTRIBUTION_TEXT, fill=(20, 20, 20, 255), font=font)

    im.save(p, "PNG")


def check_attribution_pixels_exist(img_path: str | Path) -> bool:
    """Verify that the bottom-right corner has non-blank attribution pixels."""
    im = Image.open(img_path).convert("RGB")
    w, h = im.size
    # Inspect the bottom-right corner: 280px wide by 40px high
    crop = im.crop((max(0, w - 280), max(0, h - 40), w, h))
    colors = set(crop.getdata())
    # A blank or uniform corner has very few unique colors; stamped text has many
    return len(colors) > 6


def render_location(spec: LocationSpec, out_dir: str | Path, *,
                    fps: int = 24, duration_s: float | None = None) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if duration_s is None:
        duration_s = spec.duration_s

    scene_data = build_location_scene(spec)
    write_json(out / "location_scene.json", scene_data)

    rs = RenderSize.for_aspect("16:9", spec.long_edge)
    width, height = rs.width, rs.height
    html = build_html(scene_data, width, height, fps, duration_s)

    fr = FrameRenderer(html, out, width, height, duration_s, fps)
    frames = fr.render_frames()

    still_png = out / "location_still.png"
    still_png.write_bytes(frames[0].read_bytes())
    stamp_osm_attribution(still_png)

    # If duration > 0, stamp all frames and encode mp4
    mp4_path = None
    probe = None
    if duration_s > 0 and len(frames) > 1:
        for fr_path in frames:
            stamp_osm_attribution(fr_path)
        mp4_path = encode_video(fr.frames_dir, out / f"location_{spec.time_of_day}.mp4", fps=fps)
        probe = ffprobe(mp4_path)

    cs_path = make_contact_sheet(frames, out / "location_contact_sheet.png", cols=5)

    has_attr = check_attribution_pixels_exist(still_png)
    report = {
        "lat": spec.lat,
        "lon": spec.lon,
        "time_of_day": spec.time_of_day,
        "seed": spec.seed,
        "size": {"width": width, "height": height},
        "duration_s": duration_s,
        "frame_count": len(frames),
        "attribution_present": has_attr,
        "attribution_text": OSM_ATTRIBUTION_TEXT,
        "sha256": {
            "still": sha256_file(still_png),
            "mp4": sha256_file(mp4_path) if mp4_path else None,
        },
        "contact_sheet": str(cs_path),
    }
    if probe:
        report["ffprobe"] = probe

    write_json(out / "qc_report.json", report)
    return {
        "scene": str(out / "location_scene.json"),
        "still": str(still_png),
        "mp4": str(mp4_path) if mp4_path else None,
        "report": report,
    }
