from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import types
import tempfile
import sys
import argparse

from hevi.layer4_legacy.quoteimage.oskill_impl.sentence_picker import pick_sentences
from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import command_render, command_render_script
from hevi.layer4_legacy.quoteimage.oprim_impl.whisper import WhisperAligner
from hevi.layer4_legacy.quoteimage.omodul_impl.quality_gates import run_quality_gates



def detect_subtitle_band(video_path, times):
    import numpy as np
    from PIL import ImageChops, ImageFilter
    from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import grab_frame
    
    top_min, bottom_max = 1.0, 0.0
    for t in times:
        try:
            frame = grab_frame(str(video_path), t)
            gray = frame.convert("L")
            edges = ImageChops.subtract(gray, gray.filter(ImageFilter.MinFilter(3)))
            edge_data = np.array(edges)
            row_sums = edge_data.sum(axis=1)
            
            h = edge_data.shape[0]
            bottom_start = int(h * 0.5)
            row_sums[:bottom_start] = 0
            
            window = max(1, int(h * 0.02))
            smoothed = np.convolve(row_sums, np.ones(window)/window, mode='same')
            
            threshold = np.max(smoothed) * 0.3
            text_rows = np.where(smoothed > threshold)[0]
            if len(text_rows) > 0:
                top = max(0, text_rows[0] - window) / h
                bottom = min(h, text_rows[-1] + window) / h
                top = max(0.0, top - 0.02)
                bottom = min(1.0, bottom + 0.02)
                top_min = min(top_min, top)
                bottom_max = max(bottom_max, bottom)
        except Exception:
            pass
            
    if top_min < bottom_max:
        return top_min, bottom_max
    return 0.78, 0.96

def produce_quote_image(
    *,
    video_path: Path,
    mode: str,
    strategy: str,
    output_dir: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    _enabled_pillars = {"report"}
    
    video_path = video_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    aligner = WhisperAligner()
    sentences = aligner.transcribe_segments(str(video_path))
    
    if strategy == "auto":
        picked = pick_sentences(sentences, count=4)
    elif strategy == "time_range":
        start_time = float(kwargs.get("start_time", 0))
        end_time = float(kwargs.get("end_time", 999999))
        picked = [s for s in sentences if start_time <= s["t"] <= end_time]
        if len(picked) > 6:
            picked = picked[:6]
    else:
        return {"status": "failed", "error": "Unknown strategy and no fallback allowed."}
        
    if not picked:
        return {"status": "failed", "error": "No sentences picked."}
        
    record_json_path = output_dir / "record.json"
    
    if mode == "native":
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps({
            "images": [
                {
                    "title": "quote_image",
                    "times": [s["t"] for s in picked]
                }
            ]
        }, ensure_ascii=False), encoding="utf-8")
        
        band_top = kwargs.get("band_top")
        band_bottom = kwargs.get("band_bottom")
        if band_top is None or band_bottom is None:
            band_top, band_bottom = detect_subtitle_band(video_path, [s["t"] for s in picked])
            
        args = argparse.Namespace(
            video=str(video_path),
            manifest=str(manifest_path),
            out_dir=str(output_dir),
            band_top=band_top,
            band_bottom=band_bottom,
            width=kwargs.get("width"),
            aspect=kwargs.get("aspect", (3.0, 4.0)),
            layout=kwargs.get("layout", "natural"),
            hero_fraction=kwargs.get("hero_fraction"),
            overwrite=True,
            fit=kwargs.get("fit", "crop"),
            crop_center=kwargs.get("crop_center", 0.5),
            keep_going=True,
            resume=False,
            allow_duplicate_frames=True,
        )
        try:
            command_render(args)
        except BaseException as e:
            return {"status": "failed", "error": str(e)}
            
    elif mode == "script":
        script_path = output_dir / "script.json"
        script_path.write_text(json.dumps({
            "lines": picked
        }, ensure_ascii=False), encoding="utf-8")
        
        out_img = output_dir / "quote_script.jpg"
        
        args = argparse.Namespace(
            video=str(video_path),
            script=str(script_path),
            out=str(out_img),
            aspect=kwargs.get("aspect", (3.0, 4.0)),
            width=kwargs.get("width", 1440),
            band_center=kwargs.get("band_center", 0.8),
            hero_fraction=kwargs.get("hero_fraction"),
            font=kwargs.get("font"),
            font_size=kwargs.get("font_size"),
            layout=kwargs.get("layout", "fixed"),
            frame_top=kwargs.get("frame_top", 0.0),
            frame_bottom=kwargs.get("frame_bottom", 1.0),
            overwrite=True,
            speaker_prefix="none",
            allow_duplicate_frames=True,
            six_line_card=False,
        )
        try:
            command_render_script(args)
        except BaseException as e:
            return {"status": "failed", "error": str(e)}

    # Check generated files
    images = list(output_dir.glob("*.jpg")) + list(output_dir.glob("*.png"))
    
    gates = run_quality_gates(list(output_dir.glob("*.jpg")) + list(output_dir.glob("*.png")))
    
    res = {
        "status": "succeeded",
        "mode": mode,
        "images": [str(p) for p in images],
        "records": [
            {
                "gates": gates,
                "times": [s["t"] for s in picked]
            }
        ]
    }
    record_json_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    return res
