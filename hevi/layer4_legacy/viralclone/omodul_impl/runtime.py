"""Unified entry point for ViralClone transactions (omodul layer)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.viralclone.omodul_impl.breakdown import reference_breakdown
from hevi.layer4_legacy.viralclone.omodul_impl.compiler import compile_and_render_template
from hevi.layer4_legacy.viralclone.omodul_impl.product import produce_product_asset
from hevi.layer4_legacy.viralclone.omodul_impl.variants import generate_variant_matrix

_enabled_pillars = {"report", "cost", "decision_trail"}


def produce_viralclone(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Unified 3O dispatcher for ViralClone transactions."""
    action = str(input_data.get("action") or "breakdown").lower()

    if action in ("breakdown", "reference_breakdown"):
        return reference_breakdown(config, input_data, output_dir, on_step=on_step)
    elif action in ("compile", "render", "template"):
        return compile_and_render_template(config, input_data, output_dir, on_step=on_step)
    elif action in ("product", "product_card"):
        return produce_product_asset(config, input_data, output_dir, on_step=on_step)
    elif action in ("variants", "matrix", "batch"):
        return generate_variant_matrix(config, input_data, output_dir, on_step=on_step)
    else:
        return {
            "status": "blocked",
            "reason": f"UNKNOWN_VIRALCLONE_ACTION: {action}",
            "cost": {"total_usd": 0.0, "provider": "zero_local_cpu"},
            "decision_trail": [{"step": "dispatch", "error": f"unrecognized action {action}"}],
            "report": {},
        }
