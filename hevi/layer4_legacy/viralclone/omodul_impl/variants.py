"""Variant matrix batch runner with diversity gate and AI watermark QA (omodul layer)."""

from __future__ import annotations

import concurrent.futures
import json
import os
import time
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.viralclone.omodul_impl._media import (
    _extract_frames,
    _probe_video,
    _sha256,
)
from hevi.layer4_legacy.viralclone.omodul_impl.compiler import compile_and_render_template
from hevi.layer4_legacy.viralclone.oskill_impl.diversity import (
    compute_frame_phash,
    compute_variant_diversity_matrix,
)

_enabled_pillars = {"report", "cost", "decision_trail"}


def _render_single_variant_worker(
    item: dict[str, Any],
    variant_dest: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Worker function for rendering one variant."""
    variant_id = str(item.get("variant_id") or "v_default")
    sub_dir = variant_dest / variant_id
    res = compile_and_render_template(config, item, sub_dir)
    return {"variant_id": variant_id, "result": res}


def generate_variant_matrix(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Execute batch variant matrix generation with CPU concurrency control and diversity gate."""
    t0 = time.time()
    trail: list[dict[str, Any]] = []
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)

    variant_items = list(input_data.get("variants") or [])
    if not variant_items:
        return {
            "status": "blocked",
            "reason": "NO_VARIANTS_SPECIFIED",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": [{"step": "validate_input", "error": "empty_variants"}],
            "report": {},
        }

    # CPU concurrency limit (default <= 4)
    max_workers = min(4, int(input_data.get("max_concurrency") or config.get("max_concurrency") or 4))
    trail.append({"step": "start_matrix", "count": len(variant_items), "max_workers": max_workers})

    rendered_variants: list[dict[str, Any]] = []
    try:
        # Run variants through thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_render_single_variant_worker, item, dest, config)
                for item in variant_items
            ]
            for fut in concurrent.futures.as_completed(futures):
                out = fut.result()
                rendered_variants.append(out)

        # Collect QA, sample frames, pHash, and script text for each variant
        processed_records: list[dict[str, Any]] = []
        for r in rendered_variants:
            vid = r["variant_id"]
            res = r["result"]
            if res.get("status") != "succeeded":
                trail.append({"step": "variant_failed", "variant_id": vid, "reason": res.get("reason")})
                continue

            rep = res["report"]
            vpath = Path(rep["video_path"])
            frames = [Path(p) for p in rep.get("qa_frames", [])]
            if not frames:
                frames = _extract_frames(vpath, vpath.parent / "qa_frames", fps=1.0, max_frames=6)

            # Compute pHash for each sample frame
            frame_hashes = [compute_frame_phash(f) for f in frames if f.is_file()]

            # Extract script text from input or report
            matching_input = next((it for it in variant_items if it.get("variant_id") == vid), {})
            slots = matching_input.get("slots", {})
            script_text = " ".join(str(v) for k, v in slots.items() if "line" in k or "selling" in k or "cta" in k)

            processed_records.append(
                {
                    "variant_id": vid,
                    "video_path": str(vpath),
                    "sha256": rep["sha256"],
                    "duration_s": rep["duration_s"],
                    "resolution": rep["resolution"],
                    "qa_frames": [str(f) for f in frames],
                    "frame_hashes": frame_hashes,
                    "script_text": script_text,
                    "watermark_qa": rep.get("watermark_qa", {}),
                    "metadata_qa": rep.get("metadata_qa", {}),
                }
            )

        # Diversity Gate evaluation
        diversity_records, diversity_passed = compute_variant_diversity_matrix(
            processed_records,
            min_phash_distance=int(input_data.get("min_phash_distance") or 5),
            max_text_similarity=float(input_data.get("max_text_similarity") or 0.88),
        )

        matrix_json_path = dest / "diversity_matrix.json"
        matrix_payload = {
            "all_passed": diversity_passed,
            "comparisons": [rec.to_dict() for rec in diversity_records],
            "variant_count": len(processed_records),
        }
        matrix_json_path.write_text(
            json.dumps(matrix_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        trail.append({"step": "diversity_gate", "passed": diversity_passed, "matrix": str(matrix_json_path)})

        elapsed = time.time() - t0
        report = {
            "variant_count": len(processed_records),
            "variants": processed_records,
            "diversity_matrix_json": str(matrix_json_path),
            "diversity_passed": diversity_passed,
            "elapsed_s": round(elapsed, 2),
        }

        status = "succeeded" if diversity_passed and len(processed_records) == len(variant_items) else (
            "partial" if processed_records else "failed"
        )

        return {
            "status": status,
            "report": report,
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
        }

    except Exception as exc:
        trail.append({"step": "exception", "error": str(exc)})
        return {
            "status": "failed",
            "reason": f"MATRIX_RUNNER_FAILED: {exc}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": trail,
            "report": {},
        }
