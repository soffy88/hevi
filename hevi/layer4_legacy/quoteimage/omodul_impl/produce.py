from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.quoteimage.omodul_impl.quality_gates import (
    QualityGateError,
    run_quality_gates,
)
from hevi.layer4_legacy.quoteimage.oprim_impl.detect_band import detect_subtitle_band
from hevi.layer4_legacy.quoteimage.oprim_impl.vendor_stitch import (
    command_render,
    command_render_script,
    grab_frame,
    crop_band,
)
from hevi.layer4_legacy.quoteimage.oprim_impl.whisper import WhisperAligner
from hevi.layer4_legacy.quoteimage.oskill_impl.sentence_picker import pick_sentences

logger = logging.getLogger(__name__)


def _load_script_from_source(video_path: Path) -> list[dict[str, Any]] | None:
    """Attempt to load canonical script lines from adjacent project files."""
    candidates = [
        video_path.parent / "shotbook.json",
        video_path.parent / "work" / "timestamps.json",
        video_path.parent / "timestamps.json",
        video_path.with_name("shotbook.json"),
    ]
    for c in candidates:
        if not c.is_file():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
            # shotbook format
            if "project" in data and "tracks" in data["project"]:
                lines = []
                fps = float(data["project"].get("fps", 30))
                for track in data["project"]["tracks"]:
                    if track.get("id") == "subs":
                        for clip in track.get("clips", []):
                            start_s = clip["start"] / fps
                            dur_s = clip["duration"] / fps
                            center_s = round(start_s + dur_s * 0.5, 2)
                            text = clip.get("props", {}).get("text", "").strip()
                            if text:
                                lines.append({"t": center_s, "text": text})
                if lines:
                    return lines
            # timestamps format
            if "timings" in data:
                lines = []
                for t in data["timings"]:
                    start_s = float(t.get("start_s", 0))
                    end_s = float(t.get("end_s", start_s + 2.0))
                    center_s = round(start_s + (end_s - start_s) * 0.5, 2)
                    text = t.get("text", "").strip()
                    if text:
                        lines.append({"t": center_s, "text": text})
                if lines:
                    return lines
        except Exception:
            continue
    return None


def _adjust_timestamps_for_native(
    video_path: Path,
    times: list[float],
    band_top: float,
    band_bottom: float,
) -> list[float]:
    """Ensure candidate timestamps in native mode hit active subtitles, avoiding blank transition frames."""
    adjusted = []
    for t in times:
        best_t = t
        max_edge = 0.0
        # Check around t in small increments
        for dt in (0.0, 0.4, 0.8, -0.4, 1.2):
            cand = max(0.0, t + dt)
            try:
                frame = grab_frame(str(video_path), cand)
                band, _, _ = crop_band(frame, band_top, band_bottom)
                gray = band.convert("L")
                import numpy as np
                from PIL import ImageChops, ImageFilter
                edges = ImageChops.subtract(gray, gray.filter(ImageFilter.MinFilter(3)))
                edge_val = float(np.mean(np.array(edges)))
                if edge_val > max_edge:
                    max_edge = edge_val
                    best_t = cand
                if edge_val > 4.0:
                    break
            except Exception:
                pass
        adjusted.append(round(best_t, 2))
    return adjusted


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

    # 1. Determine script lines / sentences
    picked: list[dict[str, Any]] = []

    # Check explicit kwargs first
    explicit_script = kwargs.get("script") or kwargs.get("script_path")
    if explicit_script is not None:
        if isinstance(explicit_script, (str, Path)):
            p = Path(explicit_script)
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
                picked = raw.get("lines", raw)
        elif isinstance(explicit_script, list):
            picked = explicit_script

    if not picked:
        # Check adjacent project script metadata
        script_from_file = _load_script_from_source(video_path)
        if script_from_file:
            if strategy == "auto":
                picked = pick_sentences(script_from_file, count=4)
            elif strategy == "time_range":
                if "start_time" not in kwargs or "end_time" not in kwargs:
                    return {
                        "status": "failed",
                        "error": "time_range strategy requires start_time and end_time.",
                    }
                start_time = float(kwargs["start_time"])
                end_time = float(kwargs["end_time"])
                picked = [s for s in script_from_file if start_time <= s["t"] <= end_time]
                if len(picked) > 6:
                    picked = picked[:6]
            else:
                return {"status": "failed", "error": f"Unknown strategy {strategy}"}

    if not picked:
        # Fall back to Whisper ASR
        aligner = WhisperAligner()
        sentences = aligner.transcribe_segments(str(video_path))
        if strategy == "auto":
            picked = pick_sentences(sentences, count=4)
        elif strategy == "time_range":
            if "start_time" not in kwargs or "end_time" not in kwargs:
                return {
                    "status": "failed",
                    "error": "time_range strategy requires start_time and end_time.",
                }
            start_time = float(kwargs["start_time"])
            end_time = float(kwargs["end_time"])
            picked = [s for s in sentences if start_time <= s["t"] <= end_time]
            if len(picked) > 6:
                picked = picked[:6]
        else:
            return {"status": "failed", "error": f"Unknown strategy {strategy} and no fallback allowed."}

    if not picked:
        return {"status": "failed", "error": "No sentences picked."}

    record_json_path = output_dir / "record.json"

    # Detect subtitle band in the source video
    band_top = kwargs.get("band_top")
    band_bottom = kwargs.get("band_bottom")
    if band_top is None or band_bottom is None:
        band_top, band_bottom = detect_subtitle_band(
            video_path=video_path,
            times=[s["t"] for s in picked],
        )

    if mode == "native":
        # Ensure times land on active subtitles
        times = _adjust_timestamps_for_native(video_path, [s["t"] for s in picked], band_top, band_bottom)

        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"images": [{"title": "quote_image", "times": times}]}, ensure_ascii=False),
            encoding="utf-8",
        )

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
        script_path.write_text(
            json.dumps({"lines": picked}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        out_img = output_dir / "quote_script.jpg"

        # If source has burned-in subtitles, crop above them so they don't overlap with drawn text
        frame_bottom = kwargs.get("frame_bottom")
        if frame_bottom is None:
            if band_top < 0.98:
                frame_bottom = band_top
            else:
                frame_bottom = 1.0

        band_center = kwargs.get("band_center")
        if band_center is None:
            band_center = 0.5 if frame_bottom < 0.98 else 0.6

        args = argparse.Namespace(
            video=str(video_path),
            script=str(script_path),
            out=str(out_img),
            aspect=kwargs.get("aspect", (3.0, 4.0)),
            width=kwargs.get("width"),
            band_center=band_center,
            hero_fraction=kwargs.get("hero_fraction"),
            font=kwargs.get("font", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            font_size=kwargs.get("font_size"),
            layout=kwargs.get("layout", "natural"),
            frame_top=kwargs.get("frame_top", 0.0),
            frame_bottom=frame_bottom,
            overwrite=True,
            speaker_prefix="none",
            allow_duplicate_frames=True,
            six_line_card=False,
        )
        try:
            command_render_script(args)
        except BaseException as e:
            return {"status": "failed", "error": str(e)}

    # Evaluate Quality Gates
    images = list(output_dir.glob("*.jpg")) + list(output_dir.glob("*.png"))
    gates = run_quality_gates(images)
    all_passed = bool(gates and all(g["passed"] for g in gates))

    status = "succeeded" if all_passed else "failed"

    res = {
        "status": status,
        "mode": mode,
        "images": [str(p) for p in images],
        "records": [
            {
                "gates": gates,
                "times": [s["t"] for s in picked],
            }
        ],
    }
    record_json_path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    if not all_passed:
        failed_gates = [g for g in gates if not g["passed"]]
        raise QualityGateError(f"Quality gates failed: {failed_gates}")

    return res
