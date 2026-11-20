"""Video asset imagegen gate (``qa.video_asset_imagegen_gate``).

Clean-room restatement of the补图 method of openai/codex
``imagegen`` (see ``VIDEO_SKILLS_10_ATTRIBUTION.md``); no
upstream code appears in this gate.

hevi has no imagegen capability; its image route is free-only
(Cloudflare Workers AI FLUX, Pollinations, iris.c). This gate
owns the补图 method for video: covers, illustrations,
transparent PNGs, and transition assets, each with a prompt and
a declared free route. A transparent PNG must declare its
alpha channel. The OpenAI paid API route is never accepted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

ASSET_KINDS = ("cover", "illustration", "transparent_png", "transition")
FREE_ROUTES = ("cf-flux", "pollinations", "iris-c")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_video_asset_imagegen(plan: Any) -> dict[str, Any]:
    """Validate a video asset imagegen plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when it does not declare the free
    route only, when the asset list is empty or malformed,
    when an asset kind or route is outside the closed
    vocabularies, when a transparent PNG does not declare its
    alpha channel, or when the plan names the OpenAI paid API
    route.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "asset imagegen plan must be a JSON object")
    serialized = json.dumps(plan, ensure_ascii=False).lower()
    if "openai" in serialized or "gpt-image" in serialized:
        return fail(
            "openai_route_not_accepted",
            "the OpenAI paid API route is never accepted; assets use "
            "the free route only (cf-flux, pollinations, iris-c)",
        )
    for field in ("assets", "free_route_only"):
        if field not in plan:
            return fail("plan_field_missing", f"asset imagegen plan must carry {field!r}")
    if plan["free_route_only"] is not True:
        return fail(
            "free_route_only_missing",
            "free_route_only must be declared true",
        )
    assets = plan["assets"]
    if not isinstance(assets, list) or not assets:
        return fail("assets_empty", "assets needs at least one asset")
    for asset in assets:
        if not isinstance(asset, dict):
            return fail("asset_not_object", "each asset must be an object")
        if asset.get("kind") not in ASSET_KINDS:
            return fail(
                "asset_kind_unknown",
                "asset kind must be one of: " + ", ".join(ASSET_KINDS),
            )
        if not isinstance(asset.get("prompt"), str) or not asset["prompt"]:
            return fail("asset_prompt_missing", "each asset needs a non-empty prompt")
        if asset.get("route") not in FREE_ROUTES:
            return fail(
                "asset_route_not_free",
                "asset route must be one of: " + ", ".join(FREE_ROUTES),
            )
        if asset["kind"] == "transparent_png" and asset.get("alpha") is not True:
            return fail(
                "transparent_png_alpha_missing",
                "a transparent_png asset must declare alpha true",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_video_asset_imagegen(params.get("plan"))
    report_path = out_dir / "video_asset_imagegen_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_video_asset_imagegen_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.video_asset_imagegen_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Video asset imagegen gate: covers, illustrations, "
                "transparent PNGs, and transition assets on the free route "
                "only (cf-flux, pollinations, iris-c); transparent PNGs "
                "must declare alpha; the OpenAI paid API route is never "
                "accepted."
            ),
        )
    )
    return ["qa.video_asset_imagegen_gate"]


__all__ = [
    "ASSET_KINDS",
    "FREE_ROUTES",
    "check_video_asset_imagegen",
    "register_video_asset_imagegen_gate_capabilities_once",
]
