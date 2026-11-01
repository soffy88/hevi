"""A3 reference-restoration acceptance gate (clean-room, method only).

Method source: Athenaion ``colorstats`` / side-by-side comparison
discipline as described in ``hevi-vs-athenaion.md``; see
ATHENAION_ATTRIBUTION.md. This module only *measures*: luminance
percentiles (p02/p10/p50/p90/p98), per-channel colour statistics
and saturation, plus a reference|render side-by-side image. The
target ranges are always supplied by the caller -- no author
number is written in as a default. A missing measurement, a
missing target, or a measurement outside its target range fails;
the gate never invents a value.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

PERCENTILES = (2, 10, 50, 90, 98)


def _load_rgb(path: Any) -> np.ndarray:
    p = Path(path) if not isinstance(path, Path) else path
    if not p.is_file():
        raise CapabilityError(f"qa.reference_restoration_gate: image not found: {p}")
    try:
        with Image.open(p) as image:
            return np.asarray(image.convert("RGB"), dtype=np.float64)
    except Exception as exc:
        raise CapabilityError(f"qa.reference_restoration_gate: cannot read image {p}: {exc}") from exc


def luminance_percentiles(image_path: Any) -> dict[str, float]:
    """sRGB luminance percentiles p02/p10/p50/p90/p98 (0-255 scale)."""
    rgb = _load_rgb(image_path)
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    flat = lum.ravel()
    return {f"p{p:02d}": round(float(np.percentile(flat, p)), 2) for p in PERCENTILES}


def color_stats(image_path: Any) -> dict[str, Any]:
    """Per-channel mean/std and mean saturation (HSV, 0-255 scale)."""
    rgb = _load_rgb(image_path)
    with Image.open(Path(image_path)) as image:
        hsv = np.asarray(image.convert("HSV"), dtype=np.float64)
    return {
        "mean_r": round(float(rgb[:, :, 0].mean()), 2),
        "mean_g": round(float(rgb[:, :, 1].mean()), 2),
        "mean_b": round(float(rgb[:, :, 2].mean()), 2),
        "std_r": round(float(rgb[:, :, 0].std()), 2),
        "std_g": round(float(rgb[:, :, 1].std()), 2),
        "std_b": round(float(rgb[:, :, 2].std()), 2),
        "mean_saturation": round(float(hsv[:, :, 1].mean()), 2),
        "width": int(rgb.shape[1]),
        "height": int(rgb.shape[0]),
    }


def make_comparison(reference_path: Any, render_path: Any, out_path: Any) -> Path:
    """Side-by-side comparison image: reference | render, labelled."""
    ref = Image.open(Path(reference_path)).convert("RGB")
    ren = Image.open(Path(render_path)).convert("RGB")
    resized = False
    if ren.size != ref.size:
        ren = ren.resize(ref.size, Image.BILINEAR)
        resized = True
    divider = 4
    label_h = 22
    canvas = Image.new("RGB", (ref.width * 2 + divider, ref.height + label_h), (16, 16, 20))
    canvas.paste(ref, (0, label_h))
    canvas.paste(ren, (ref.width + divider, label_h))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, ref.width, label_h], fill=(16, 16, 20))
    draw.rectangle([ref.width + divider, 0, canvas.width, label_h], fill=(16, 16, 20))
    draw.text((6, 5), "reference", fill=(255, 255, 255))
    draw.text((ref.width + divider + 6, 5), "render", fill=(255, 255, 255))
    draw.rectangle([ref.width, label_h, ref.width + divider, canvas.height], fill=(255, 200, 60))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def check_restoration(
    reference_path: Any,
    render_path: Any,
    targets: Any,
    *,
    out_cmp_path: Any = None,
) -> dict[str, Any]:
    """Judge measured values against caller-supplied targets only."""
    if not isinstance(targets, dict) or not targets:
        raise CapabilityError(
            "qa.reference_restoration_gate: 'targets' must be a non-empty object "
            "mapping percentile names to [lo, hi] ranges supplied by the caller"
        )
    issues: list[dict[str, Any]] = []
    measured = luminance_percentiles(render_path)
    stats = color_stats(render_path)
    ref_stats = color_stats(reference_path)
    for name in (f"p{p:02d}" for p in PERCENTILES):
        target = targets.get(name)
        if target is None:
            issues.append({
                "code": "target_missing",
                "message": f"no caller-supplied target for {name}; a missing target fails, it is not defaulted",
                "percentile": name,
            })
            continue
        if (
            not isinstance(target, (list, tuple)) or len(target) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in target)
        ):
            issues.append({
                "code": "target_malformed",
                "message": f"target for {name} must be [lo, hi]",
                "percentile": name, "target": target,
            })
            continue
        lo, hi = float(target[0]), float(target[1])
        value = measured[name]
        if not lo <= value <= hi:
            issues.append({
                "code": "percentile_out_of_range",
                "message": f"{name} measured {value} outside caller target [{lo}, {hi}]",
                "percentile": name, "measured": value, "target": [lo, hi],
            })
    cmp_path = None
    if out_cmp_path is not None:
        cmp_path = str(make_comparison(reference_path, render_path, out_cmp_path))
    return {
        "verdict": "fail" if issues else "pass",
        "issues": issues,
        "measured_percentiles": measured,
        "render_color_stats": stats,
        "reference_color_stats": ref_stats,
        "targets": targets,
        "comparison_path": cmp_path,
        "comparison_resized_render": bool(cmp_path) and (
            Image.open(Path(reference_path)).size != Image.open(Path(render_path)).size
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reference = params.get("reference_path")
    render = params.get("render_path")
    if not reference or not render:
        raise CapabilityError(
            "qa.reference_restoration_gate: reference_path and render_path are required"
        )
    report = check_restoration(
        reference, render, params.get("targets"),
        out_cmp_path=out_dir / "comparison.png",
    )
    report_path = out_dir / "restoration_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        png=str(out_dir / "comparison.png"),
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "ok": report["verdict"] == "pass",
            "issues": report["issues"],
            "measured_percentiles": report["measured_percentiles"],
        },
    )


def register_athenaion_restoration_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.reference_restoration_gate",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "reference_path": {"type": "string"},
                "render_path": {"type": "string"},
                "targets": {"type": "object"},
            },
            "required": ["reference_path", "render_path", "targets"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.01,
        render=_render,
        has_media_output=False,
        description=(
            "A3 reference-restoration gate: side-by-side comparison "
            "image plus measured luminance percentiles and colour "
            "statistics, judged only against caller-supplied targets. "
            "Missing measurements or targets fail. See ATHENAION_ATTRIBUTION.md."
        ),
        line="qa",
    ))
    return ["qa.reference_restoration_gate"]


register_athenaion_restoration_capabilities_once()
