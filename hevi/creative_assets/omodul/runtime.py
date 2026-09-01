"""Visual asset plan/execute boundary with truthful artifact reporting."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hevi.creative_assets.oprim.contracts import VisualAssetPlan, VisualAssetRequest
from hevi.creative_assets.oskill.compiler import compile_visual_prompt, default_aspect_ratio


def _size_for_ratio(ratio: str) -> str:
    return {
        "16:9": "1280*720",
        "9:16": "720*1280",
        "1:1": "1024*1024",
        "4:5": "1024*1280",
        "3:4": "960*1280",
        "4:3": "1280*960",
    }.get(ratio, "1280*720")


def plan_visual_asset(request: VisualAssetRequest) -> VisualAssetPlan:
    issues = request.validate()
    ratio = request.aspect_ratio or default_aspect_ratio(request.platform)
    prompt = compile_visual_prompt(request)
    return VisualAssetPlan(
        request=request,
        prompt=prompt,
        size=_size_for_ratio(ratio),
        status="blocked" if issues else "planned",
        errors=tuple(issues),
    )


async def execute_visual_asset(
    request: VisualAssetRequest,
    *,
    output_path: str | Path,
    provider: str = "auto",
) -> dict[str, Any]:
    """Generate only through a configured real image provider and verify the file."""

    plan = plan_visual_asset(request)
    destination = Path(output_path).expanduser()
    if plan.status == "blocked":
        return {**plan.to_dict(), "status": "blocked"}
    if request.prompt_only:
        return {**plan.to_dict(), "status": "planned", "output_path": None}
    selected = provider
    if selected == "auto":
        selected = os.getenv("HEVI_VISUAL_ASSET_PROVIDER", "").strip() or ""
    if not selected:
        return {
            **plan.to_dict(),
            "status": "blocked",
            "errors": ["no image provider configured; plan retained, no artifact created"],
        }

    try:
        from obase.provider_registry import ProviderRegistry

        generator = ProviderRegistry.get().image_gen(selected)
    except Exception as exc:
        return {**plan.to_dict(), "status": "blocked", "errors": [f"provider unavailable: {exc}"]}
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        result: Any = generator(
            prompt=plan.prompt,
            output_path=destination,
            size=plan.size,
            reference_image=request.reference_path,
        )
        if hasattr(result, "__await__"):
            result = await result
        if not destination.is_file() or destination.stat().st_size <= 0:
            return {
                **plan.to_dict(),
                "status": "failed",
                "errors": ["image provider returned without a verified local artifact"],
                "provider": selected,
            }
        return {
            **plan.to_dict(),
            "status": "completed",
            "output_path": str(destination),
            "provider": selected,
            "provider_result": str(result),
        }
    except Exception as exc:
        return {**plan.to_dict(), "status": "failed", "errors": [str(exc)], "provider": selected}


__all__ = ["execute_visual_asset", "plan_visual_asset"]
