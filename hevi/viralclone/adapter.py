"""Public adapter interface for ViralClone (HEVI exterior shim)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.layer4_legacy.viralclone.omodul_impl.breakdown import reference_breakdown
from hevi.layer4_legacy.viralclone.omodul_impl.compiler import (
    compile_and_render_template,
    draft_template_from_breakdown,
)
from hevi.layer4_legacy.viralclone.omodul_impl.product import produce_product_asset
from hevi.layer4_legacy.viralclone.omodul_impl.runtime import produce_viralclone
from hevi.layer4_legacy.viralclone.omodul_impl.variants import generate_variant_matrix


def breakdown_reference_video(
    video_path: str | Path,
    output_dir: str | Path,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Breakdown a reference video into breakdown.json, contactsheet.jpg, and breakdown.md."""
    cfg = config or {}
    inp = {"video_path": str(video_path)}
    return reference_breakdown(cfg, inp, output_dir)


def compile_viral_template(
    template: dict[str, Any] | str | Path,
    slots: dict[str, Any],
    output_dir: str | Path,
    *,
    brolls: list[str] | None = None,
    product_video: str | None = None,
    aspect_ratio: str = "9:16",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile a word-anchored template with slot variables into Timeline JSON and render MP4."""
    cfg = config or {}
    inp = {
        "template": template if isinstance(template, dict) else str(template),
        "slots": slots,
        "brolls": brolls or [],
        "product_video": product_video or "",
        "aspect_ratio": aspect_ratio,
    }
    return compile_and_render_template(cfg, inp, output_dir)


def render_viral_variants(
    variants: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    max_concurrency: int = 4,
    min_phash_distance: int = 5,
    max_text_similarity: float = 0.88,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Batch generate multiple variants with CPU concurrency and diversity gate."""
    cfg = config or {}
    inp = {
        "variants": variants,
        "max_concurrency": max_concurrency,
        "min_phash_distance": min_phash_distance,
        "max_text_similarity": max_text_similarity,
    }
    return generate_variant_matrix(cfg, inp, output_dir)


def produce_product_card_video(
    product_image: str | Path,
    output_dir: str | Path,
    *,
    product_title: str = "精选爆款正品",
    price_tag: str = "¥99",
    cta_text: str = "立即抢购",
    selling_points: list[str] | None = None,
    aspect_ratio: str = "9:16",
    duration_s: float = 3.0,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Remove background and render product card video."""
    cfg = config or {}
    w, h = (720, 1280) if aspect_ratio == "9:16" else (1280, 720)
    inp = {
        "product_image": str(product_image),
        "product_title": product_title,
        "price_tag": price_tag,
        "cta_text": cta_text,
        "selling_points": selling_points or ["官方正品", "权威实测", "极速发货"],
        "width": w,
        "height": h,
        "duration_s": duration_s,
    }
    return produce_product_asset(cfg, inp, output_dir)
