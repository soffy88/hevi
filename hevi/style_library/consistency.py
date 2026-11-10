"""Whole-film style lock and frame drift checks.

The lock records one style id and one theme colour for a film.  Drift is
measured on the rendered frames with a colour histogram distance (always
available, PIL + numpy).  A CLIP embedding check is attempted when a local
CLIP scorer is installed; when it is not, the report says ``color_only``
instead of pretending the semantic check ran.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from hevi.style_library import catalog

DEFAULT_THRESHOLD = 0.18


def lock(style_id: str, theme_color_id: str = "C-27", *, scope: str = "film") -> dict[str, Any]:
    style = catalog.get_style(style_id)
    color = catalog.get_color(theme_color_id)
    return {
        "scope": scope,
        "style_id": style["id"],
        "style_name": style.get("generation_name", ""),
        "theme_color_id": color["id"],
        "theme_color_name": color.get("name_zh", ""),
        "theme_hex": color.get("hex", ""),
        "palette": catalog.theme_palette(color["id"]),
        "attribution": catalog.ATTRIBUTION,
    }


def _histogram(path: str | Path, bins: int = 16) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    image.thumbnail((320, 320))
    arr = np.asarray(image, dtype=np.float32) / 255.0
    hist, _ = np.histogramdd(
        arr.reshape(-1, 3), bins=(bins, bins, bins), range=((0, 1), (0, 1), (0, 1))
    )
    hist = hist.ravel().astype(np.float64)
    total = hist.sum()
    return hist / total if total else hist


def _hist_distance(a: np.ndarray, b: np.ndarray) -> float:
    # Bhattacharyya distance, 0 = identical.
    bc = float(np.sum(np.sqrt(a * b)))
    return max(0.0, min(1.0, 1.0 - bc))


def _mean_rgb(path: str | Path) -> list[int]:
    image = Image.open(path).convert("RGB")
    image.thumbnail((160, 160))
    arr = np.asarray(image, dtype=np.float32)
    return [round(v) for v in arr.reshape(-1, 3).mean(axis=0)]


def _clip_embedding(path: str | Path) -> np.ndarray | None:
    """Best-effort local CLIP embedding; None when no scorer is installed."""
    try:  # pragma: no cover - depends on the deployment image
        import torch
        from transformers import CLIPModel, CLIPProcessor
    except Exception:
        return None
    try:  # pragma: no cover
        model_dir = "/data/soffy/models/ms/models/openai--clip-vit-base-patch32/snapshots/master"
        model = CLIPModel.from_pretrained(model_dir).eval()  # type: ignore[no-untyped-call]
        proc = CLIPProcessor.from_pretrained(model_dir)
        image = Image.open(path).convert("RGB")
        with torch.no_grad():
            inputs = proc(images=image, return_tensors="pt")
            vec = np.asarray(model.get_image_features(**inputs)[0].numpy())
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec
    except Exception:
        return None


def check_frames(
    frames: Iterable[str | Path],
    *,
    reference: str | Path | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    seconds_per_frame: float | None = None,
    semantic: bool = True,
) -> dict[str, Any]:
    paths = [Path(p) for p in frames]
    paths = [p for p in paths if p.is_file()]
    if not paths:
        return {"ok": False, "error": "no frames", "frames": [], "rerender": []}
    ref_path = Path(reference) if reference else paths[0]
    ref_hist = _histogram(ref_path)
    ref_clip = _clip_embedding(ref_path) if semantic else None
    rows: list[dict[str, Any]] = []
    rerender: list[int] = []
    for idx, path in enumerate(paths):
        hist = _histogram(path)
        dist = _hist_distance(ref_hist, hist)
        row: dict[str, Any] = {
            "index": idx,
            "frame": str(path),
            "color_distance": round(dist, 4),
            "mean_rgb": _mean_rgb(path),
            "over_threshold": dist > threshold,
        }
        if seconds_per_frame is not None:
            row["seconds"] = round(idx * seconds_per_frame, 3)
        clip = _clip_embedding(path) if semantic else None
        if ref_clip is not None and clip is not None:
            row["clip_distance"] = round(1.0 - float(np.dot(ref_clip, clip)), 4)
            row["over_threshold"] = bool(
                row["over_threshold"] or row["clip_distance"] > 0.22
            )
        if row["over_threshold"]:
            rerender.append(idx)
        rows.append(row)
    return {
        "ok": not rerender,
        "method": "color+clip" if ref_clip is not None else "color_only",
        "threshold": threshold,
        "reference": str(ref_path),
        "frames": rows,
        "rerender": rerender,
        "rerender_count": len(rerender),
    }


def plan_rerender(report: dict[str, Any], *, fps: float = 24.0) -> dict[str, Any]:
    """Only the over-threshold frames, merged into contiguous runs."""
    indices = sorted(int(i) for i in report.get("rerender") or [])
    runs: list[dict[str, Any]] = []
    for i in indices:
        if runs and i == runs[-1]["end_frame"] + 1:
            runs[-1]["end_frame"] = i
            runs[-1]["end_s"] = round((i + 1) / fps, 3)
        else:
            runs.append({
                "start_frame": i,
                "end_frame": i,
                "start_s": round(i / fps, 3),
                "end_s": round((i + 1) / fps, 3),
            })
    return {"fps": fps, "runs": runs, "frame_count": len(indices)}


__all__ = ["DEFAULT_THRESHOLD", "check_frames", "lock", "plan_rerender"]
