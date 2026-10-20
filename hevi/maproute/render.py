"""Chromium frame-by-frame renderer for the map-route line.

Pipeline: shot table -> geocode (geo.py) -> route (OSRM / AMap) ->
timeline milestones (timeline.py) -> basemap tiles stitched with PIL ->
an HTML page whose canvas draws *one deterministic frame per time t*
(``window.__renderAt(t)``) -> Playwright/Chromium screenshots each frame
(the same seek-and-shoot approach as hevi's HyperFrames line,
``hevi/video/csk_styled_render.py``) -> ffmpeg encodes the MP4.

Basemap: Esri World Street Map tiles (free, key-less for this use;
attribution on-frame).  Measured from ubuntu26 on 2026-10-20:
tile.openstreetmap.org and OpenTopoMap time out (curl 000), and CARTO
basemaps answers 200 but serves "API KEY REQUIRED" watermark placeholder
tiles (caught by frame inspection of the first pilot — unusable), while
server.arcgisonline.com serves real street-map tiles.  A PIL-drawn vector
graticule sheet remains the fallback when every tile download fails.
The *route* itself always comes
from a real routing engine (or an explicit ``route_polyline`` in the shot
table); a tile failure never fakes a route.
"""

from __future__ import annotations

import io
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from .errors import MapRouteError
from .geo import (
    cumulative_fractions,
    fetch_route,
    fraction_at_point,
    geocode_place,
    latlon_to_world_px,
)
from .schema import validate_shot_table
from .timeline import build_timeline

Fetcher = Callable[[str, dict], bytes]
# Esri World Street Map tile endpoint: path order is /tile/{z}/{y}/{x}.
TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
TILE_ATTRIBUTION = "Esri World Street Map, (c) OpenStreetMap contributors"
_ASPECT_SIZE = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960)}


# ------------------------------------------------------------------- tiles

def _choose_zoom(lons: list[float], lats: list[float], max_px: int = 2200) -> int:
    for z in range(15, 4, -1):
        xs = [latlon_to_world_px(lat, lon, z)[0] for lon, lat in zip(lons, lats)]
        ys = [latlon_to_world_px(lat, lon, z)[1] for lon, lat in zip(lons, lats)]
        if max(xs) - min(xs) <= max_px and max(ys) - min(ys) <= max_px:
            return z
    return 5


def _stitch_basemap(
    polyline: list[list[float]], work_dir: Path, *, fetcher: Fetcher
) -> dict[str, Any]:
    """Download + stitch CARTO tiles covering the route; PIL vector fallback."""
    from PIL import Image, ImageDraw

    lons = [p[0] for p in polyline]
    lats = [p[1] for p in polyline]
    zoom = _choose_zoom(lons, lats)
    pad_frac = 0.30
    xs = [latlon_to_world_px(lat, lon, zoom)[0] for lon, lat in zip(lons, lats)]
    ys = [latlon_to_world_px(lat, lon, zoom)[1] for lon, lat in zip(lons, lats)]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad_x = max(40.0, (x1 - x0) * pad_frac)
    pad_y = max(40.0, (y1 - y0) * pad_frac)
    x0, y0 = x0 - pad_x, y0 - pad_y
    x1, y1 = x1 + pad_x, y1 + pad_y
    # Keep the sheet wide enough that a 16:9 follow camera near the route
    # ends still sits on map, not on paper background.
    min_w = (y1 - y0) * 1.15
    if x1 - x0 < min_w:
        mid = (x0 + x1) / 2
        x0, x1 = mid - min_w / 2, mid + min_w / 2
    tx0, ty0 = int(x0 // 256), int(y0 // 256)
    tx1, ty1 = int(x1 // 256), int(y1 // 256)
    width = (tx1 - tx0 + 1) * 256
    height = (ty1 - ty0 + 1) * 256
    canvas = Image.new("RGB", (width, height), (242, 239, 231))
    failures = 0
    tiles = 0
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            tiles += 1
            url = TILE_URL.format(z=zoom, x=tx, y=ty)  # template orders z/y/x
            try:
                raw = fetcher(url, {"User-Agent": "hevi-maproute/1.0"})
                tile = Image.open(io.BytesIO(raw)).convert("RGB")
                canvas.paste(tile, ((tx - tx0) * 256, (ty - ty0) * 256))
            except Exception:  # noqa: BLE001 - counted; paper colour remains
                failures += 1
    origin_x = tx0 * 256
    origin_y = ty0 * 256
    crop = canvas.crop(
        (int(x0 - origin_x), int(y0 - origin_y), int(x1 - origin_x), int(y1 - origin_y))
    )
    used_tiles = failures < tiles
    if not used_tiles:
        # Vector fallback sheet: graticule over paper background.
        draw = ImageDraw.Draw(crop)
        step_px = max(48, min(crop.width, crop.height) // 8)
        for gx in range(0, crop.width, step_px):
            draw.line([(gx, 0), (gx, crop.height)], fill=(216, 210, 196), width=1)
        for gy in range(0, crop.height, step_px):
            draw.line([(0, gy), (crop.width, gy)], fill=(216, 210, 196), width=1)
    path = work_dir / "base_map.png"
    crop.save(path)
    return {
        "path": path,
        "zoom": zoom,
        "origin_x": x0,
        "origin_y": y0,
        "width": crop.width,
        "height": crop.height,
        "tiles": tiles,
        "tile_failures": failures,
        "source": "esri" if used_tiles else "vector-fallback",
    }


# -------------------------------------------------------------------- HTML

_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#f2efe7;overflow:hidden}
canvas{display:block}</style></head><body>
<canvas id="map" width="__W__" height="__H__"></canvas>
<script>
const DATA = __DATA__;
const baseImg = new Image();
let baseReady = false;
baseImg.onload = () => { baseReady = true; };
baseImg.src = "base_map.png";
const cv = document.getElementById("map"), ctx = cv.getContext("2d");
const W = cv.width, H = cv.height;
function fracAt(t){
  const ms = DATA.milestones;
  if (t <= ms[0][0]) return ms[0][1];
  for (let i=1;i<ms.length;i++){
    if (t <= ms[i][0]){ const [t0,f0]=ms[i-1],[t1,f1]=ms[i];
      return t1>t0 ? f0+(f1-f0)*(t-t0)/(t1-t0) : f1; }
  }
  return ms[ms.length-1][1];
}
function pointAt(frac){
  const pts = DATA.routePx, fr = DATA.routeFrac;
  if (frac <= 0) return pts[0];
  for (let i=1;i<fr.length;i++){
    if (fr[i] >= frac){ const span = fr[i]-fr[i-1];
      const k = span>0 ? (frac-fr[i-1])/span : 0;
      return [pts[i-1][0]+(pts[i][0]-pts[i-1][0])*k,
              pts[i-1][1]+(pts[i][1]-pts[i-1][1])*k]; }
  }
  return pts[pts.length-1];
}
function legAt(frac){
  const sf = DATA.stopFrac; let k = 0;
  for (let i=0;i<sf.length;i++){ if (frac >= sf[i]-1e-9) k = i; }
  return Math.min(k, sf.length-2);
}
function draw(t){
  const frac = fracAt(t), head = pointAt(frac);
  const leg = legAt(frac), sf = DATA.stopFrac;
  const legSpan = Math.max(1e-6, sf[leg+1]-sf[leg]);
  const legP = Math.min(1, Math.max(0, (frac-sf[leg])/legSpan));
  const mode = (frac <= 0 && t < DATA.arrivals[1]) ? DATA.stops[0].camera
             : DATA.stops[leg+1].camera;
  const fit = Math.min(W/(DATA.baseW*1.02), H/(DATA.baseH*1.02));
  let cx = DATA.centroid[0], cy = DATA.centroid[1], scale = fit;
  if (mode === "follow"){ cx = head[0]; cy = head[1]; scale = fit*1.9; }
  else if (mode === "dive"){
    const e = 1-Math.pow(1-legP, 2);
    cx = DATA.centroid[0]+(head[0]-DATA.centroid[0])*e;
    cy = DATA.centroid[1]+(head[1]-DATA.centroid[1])*e;
    scale = fit*(0.55+0.75*e);
  }
  ctx.setTransform(1,0,0,1,0,0);
  ctx.fillStyle = "#f2efe7"; ctx.fillRect(0,0,W,H);
  ctx.setTransform(scale,0,0,scale, W/2-cx*scale, H/2-cy*scale);
  if (baseReady) ctx.drawImage(baseImg, DATA.baseOrigin[0], DATA.baseOrigin[1]);
  const lw = (px) => px/scale;
  const trace = (upto) => {
    ctx.beginPath();
    const pts = DATA.routePx; let started=false;
    for (let i=0;i<pts.length;i++){
      const f = DATA.routeFrac[i];
      if (f <= upto){ if(!started){ctx.moveTo(pts[i][0],pts[i][1]);started=true;}
        else ctx.lineTo(pts[i][0],pts[i][1]); }
      else { const h = pointAt(upto); ctx.lineTo(h[0],h[1]); break; }
    }
    if (upto >= 1) { const l = pts[pts.length-1]; ctx.lineTo(l[0],l[1]); }
    ctx.stroke();
  };
  ctx.lineJoin="round"; ctx.lineCap="round";
  ctx.strokeStyle="#ffffff"; ctx.lineWidth=lw(11); trace(1);
  ctx.strokeStyle="#b9c6d2"; ctx.lineWidth=lw(6); trace(1);
  ctx.strokeStyle="#e63946"; ctx.lineWidth=lw(6.5); trace(frac);
  DATA.stops.forEach((s, i) => {
    const p = DATA.stopPx[i], reached = frac >= sf[i]-1e-9 || i===0;
    ctx.beginPath(); ctx.arc(p[0], p[1], lw(11), 0, 7);
    ctx.fillStyle = reached ? "#e63946" : "#8a97a5"; ctx.fill();
    ctx.lineWidth = lw(3.5); ctx.strokeStyle="#fff"; ctx.stroke();
    ctx.fillStyle="#fff"; ctx.font = `700 ${lw(13)}px "Noto Sans CJK SC", sans-serif`;
    ctx.textAlign="center"; ctx.textBaseline="middle";
    ctx.fillText(String(i+1), p[0], p[1]+lw(1));
    ctx.font = `700 ${lw(19)}px "Noto Sans CJK SC", sans-serif`;
    const label = s.name, tw = ctx.measureText(label).width;
    const lx = p[0], ly = p[1]-lw(30);
    ctx.fillStyle="rgba(255,255,255,0.88)";
    ctx.beginPath(); ctx.roundRect(lx-tw/2-lw(8), ly-lw(14), tw+lw(16), lw(28), lw(8)); ctx.fill();
    ctx.fillStyle="#20303c"; ctx.fillText(label, lx, ly+lw(1));
  });
  const pulse = 13 + 4*Math.sin(t*4);
  ctx.beginPath(); ctx.arc(head[0], head[1], lw(pulse), 0, 7);
  ctx.strokeStyle="rgba(230,57,70,0.45)"; ctx.lineWidth=lw(3); ctx.stroke();
  ctx.beginPath(); ctx.arc(head[0], head[1], lw(6), 0, 7);
  ctx.fillStyle="#e63946"; ctx.fill();
  ctx.lineWidth=lw(2.5); ctx.strokeStyle="#fff"; ctx.stroke();
  // screen-space overlays
  ctx.setTransform(1,0,0,1,0,0);
  ctx.fillStyle="rgba(24,34,44,0.82)";
  ctx.beginPath(); ctx.roundRect(18, 16, Math.min(W-36, 34+DATA.title.length*25), 52, 12); ctx.fill();
  ctx.fillStyle="#fff"; ctx.font='700 25px "Noto Sans CJK SC", sans-serif';
  ctx.textAlign="left"; ctx.textBaseline="middle";
  ctx.fillText(DATA.title, 36, 43);
  let cur = DATA.stops[DATA.stops.length-1];
  for (let i=0;i<DATA.arrivals.length;i++){ if (t <= DATA.arrivals[i]) { cur = DATA.stops[i]; break; } }
  const caption = cur.narration ? `${cur.name} · ${cur.narration}` : cur.name;
  ctx.fillStyle="rgba(24,34,44,0.82)";
  ctx.beginPath(); ctx.roundRect(18, H-96, W-36, 52, 12); ctx.fill();
  ctx.fillStyle="#fff"; ctx.font='500 21px "Noto Sans CJK SC", sans-serif';
  ctx.fillText(caption, 36, H-69, W-72);
  ctx.fillStyle="rgba(24,34,44,0.25)"; ctx.fillRect(18, H-30, W-36, 7);
  ctx.fillStyle="#e63946"; ctx.fillRect(18, H-30, (W-36)*frac, 7);
  ctx.fillStyle="#42505c"; ctx.font='500 15px "Noto Sans CJK SC", sans-serif';
  ctx.textAlign="right";
  const km = (DATA.distanceKm*frac).toFixed(0), tot = DATA.distanceKm.toFixed(0);
  ctx.fillText(`${km} / ${tot} km`, W-20, H-112);
  ctx.textAlign="left"; ctx.fillStyle="#7a8794";
  ctx.fillText(DATA.attribution, 20, 86);
  ctx.fillStyle="#42505c"; ctx.font='700 17px "Noto Sans CJK SC", sans-serif';
  ctx.textAlign="center"; ctx.fillText("N ↑", W-42, 40);
  return {frac, mode};
}
window.__renderAt = (t) => draw(t);
window.__ready = () => baseReady;
</script></body></html>
"""


# ----------------------------------------------------------------- capture

def _capture_frames_chromium(
    html_path: Path, frames_dir: Path, *, fps: int, total_s: float, width: int, height: int
) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - env guard
        raise MapRouteError(f"playwright unavailable for chromium capture: {exc}") from exc
    frames_dir.mkdir(parents=True, exist_ok=True)
    total_frames = max(2, int(round(total_s * fps)))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(html_path.as_uri())
            try:
                page.wait_for_function("window.__ready && window.__ready()", timeout=15000)
            except Exception:  # noqa: BLE001 - vector fallback has no tiles to wait for
                page.wait_for_timeout(400)
            for idx in range(total_frames):
                t = idx / fps
                page.evaluate(f"window.__renderAt({t:.4f})")
                page.wait_for_timeout(25)
                page.screenshot(path=str(frames_dir / f"frame_{idx:04d}.png"))
        finally:
            browser.close()
    return total_frames


def _encode_mp4(frames_dir: Path, output: Path, *, fps: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MapRouteError("ffmpeg not found on PATH (needed for mp4 encoding)")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-framerate", str(fps), "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
        str(output),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not output.exists():
        raise MapRouteError(f"ffmpeg encode failed: {(proc.stderr or '')[-800:]}")


# -------------------------------------------------------------------- main

def render_map_route(
    spec_in: dict[str, Any],
    out_dir: Path,
    *,
    aspect: str = "16:9",
    alignment: Any = None,
    fetcher: Optional[Fetcher] = None,
    capture_fn: Optional[Callable[..., int]] = None,
) -> dict[str, Any]:
    """Render a shot table to ``out_dir/map_route.mp4`` (+ sidecar data)."""
    spec = validate_shot_table(spec_in)
    fetcher = fetcher or _default_fetcher()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "maproute_work"
    work.mkdir(parents=True, exist_ok=True)
    width, height = _ASPECT_SIZE.get(aspect, _ASPECT_SIZE["16:9"])

    # 1) Resolve stop coordinates.
    resolved: list[dict[str, Any]] = []
    coords: list[tuple[float, float]] = []
    for stop in spec["stops"]:
        if stop["lat"] is not None:
            entry = {**stop, "lon": stop["lon"], "source": "shot-table"}
        else:
            hit = geocode_place(stop["name"], provider=spec["provider"], fetcher=fetcher)
            entry = {**stop, "lat": hit["lat"], "lon": hit["lon"], "source": hit["source"]}
        resolved.append(entry)
        coords.append((entry["lon"], entry["lat"]))

    # 2) Route geometry.
    if spec["route_polyline"]:
        polyline = spec["route_polyline"]
        distance_m = 0.0
        for i in range(1, len(polyline)):
            from .geo import haversine_m

            distance_m += haversine_m(
                (polyline[i - 1][0], polyline[i - 1][1]), (polyline[i][0], polyline[i][1])
            )
        route_info = {"source": "shot-table-polyline", "distance_m": distance_m, "duration_s": 0.0}
    else:
        route = fetch_route(
            coords, provider=spec["provider"], profile=spec["profile"], fetcher=fetcher
        )
        polyline = route["polyline"]
        route_info = {
            "source": route["source"],
            "distance_m": route["distance_m"],
            "duration_s": route["duration_s"],
        }

    fractions = cumulative_fractions(polyline)
    stop_fractions = [
        0.0 if i == 0 else 1.0 if i == len(coords) - 1 else fraction_at_point(
            polyline, fractions, lon, lat
        )
        for i, (lon, lat) in enumerate(coords)
    ]
    stop_fractions = sorted(stop_fractions)
    stop_fractions[0], stop_fractions[-1] = 0.0, 1.0

    # 3) Timeline (alignment-driven or dwell-driven).
    timeline = build_timeline(
        resolved,
        stop_fractions,
        alignment=alignment,
        total_duration_s=spec["total_duration_s"],
    )
    total_s = float(timeline["total_duration_s"])
    fps = int(spec["fps"])

    # 4) Basemap + frame data in world-pixel space.
    base = _stitch_basemap(polyline, work, fetcher=fetcher)
    zoom = base["zoom"]

    def to_px(lon: float, lat: float) -> list[float]:
        x, y = latlon_to_world_px(lat, lon, zoom)
        return [x - base["origin_x"], y - base["origin_y"]]

    route_px = [to_px(p[0], p[1]) for p in polyline]
    data = {
        "title": spec["title"],
        "stops": [
            {"name": s["name"], "camera": s["camera"], "narration": s["narration"]}
            for s in resolved
        ],
        "stopPx": [to_px(s["lon"], s["lat"]) for s in resolved],
        "stopFrac": stop_fractions,
        "routePx": route_px,
        "routeFrac": fractions,
        "milestones": [[t, f] for t, f in timeline["milestones"]],
        "arrivals": timeline["arrival_times_s"],
        "baseW": base["width"],
        "baseH": base["height"],
        "baseOrigin": [0, 0],
        "centroid": [
            sum(p[0] for p in route_px) / len(route_px),
            sum(p[1] for p in route_px) / len(route_px),
        ],
        "distanceKm": route_info["distance_m"] / 1000.0,
        "attribution": (
            f"{TILE_ATTRIBUTION} | route: {route_info['source']}"
            if base["source"] == "esri"
            else f"vector basemap (tiles unreachable) | route: {route_info['source']}"
        ),
    }
    html = (
        _HTML.replace("__W__", str(width))
        .replace("__H__", str(height))
        .replace("__DATA__", json.dumps(data, ensure_ascii=False))
    )
    html_path = work / "index.html"
    html_path.write_text(html, encoding="utf-8")

    # 5) Capture + encode.
    frames_dir = work / "frames"
    capture = capture_fn or _capture_frames_chromium
    n_frames = capture(
        html_path, frames_dir, fps=fps, total_s=total_s, width=width, height=height
    )
    mp4 = out_dir / "map_route.mp4"
    _encode_mp4(frames_dir, mp4, fps=fps)
    if not mp4.is_file() or mp4.stat().st_size == 0:
        raise MapRouteError("render produced no mp4")

    sidecar = {
        "title": spec["title"],
        "provider": spec["provider"],
        "profile": spec["profile"],
        "stops": [
            {
                "name": s["name"], "lat": s["lat"], "lon": s["lon"],
                "source": s["source"], "camera": s["camera"],
                "narration": s["narration"], "route_fraction": f,
            }
            for s, f in zip(resolved, stop_fractions)
        ],
        "route": route_info,
        "basemap": {
            "source": base["source"], "zoom": zoom,
            "tiles": base["tiles"], "tile_failures": base["tile_failures"],
        },
        "timeline": {
            "mode": timeline["mode"],
            "total_duration_s": total_s,
            "milestones": [[t, f] for t, f in timeline["milestones"]],
            "notes": timeline["notes"],
        },
        "engine": "chromium" if capture_fn is None else "injected-capture",
        "fps": fps,
        "frames": n_frames,
        "width": width,
        "height": height,
        "cost": "free: no paid calls (OSM/Photon/OSRM/CARTO public endpoints)",
    }
    (out_dir / "maproute_sidecar.json").write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"mp4": str(mp4), "duration_s": total_s, "sidecar": sidecar}


def _default_fetcher() -> Fetcher:
    from .geo import default_fetcher

    return default_fetcher


__all__ = ["render_map_route"]
