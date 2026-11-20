"""Workflow bundle gate (``qa.freevideo_workflow_bundle_gate``).

A video that travels with its workflow can be rebuilt and
checked: prompt, seed, and settings ride with the file, and
a ComfyUI canvas can restore them. In the reviewer's own
words, a bundle fails when the video id, the prompt, the
seed, the settings, or the workflow file is missing, or when
the source is not traceable. The gate judges bundle
descriptions only; it never renders or restores a workflow.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here.
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


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_freevideo_workflow_bundle(bundle: Any) -> dict[str, Any]:
    """Validate a FreeVideo-style self-carried workflow bundle.

    Verdicts are ``pass`` / ``fail`` only. A bundle fails
    when it is not an object, when the video id, prompt,
    seed, settings, or workflow file is missing or empty,
    or when the source is not traceable.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(bundle, dict):
        return fail("bundle_not_object", "workflow bundle must be a JSON object")
    video_id = bundle.get("video_id")
    if not isinstance(video_id, str) or not video_id:
        return fail("video_id_missing", "workflow bundle must carry a video_id")
    prompt = bundle.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return fail("prompt_missing", "workflow bundle must carry a prompt")
    seed = bundle.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        return fail("seed_invalid", "workflow bundle must carry an integer seed")
    settings = bundle.get("settings")
    if not isinstance(settings, dict) or not settings:
        return fail("settings_missing", "workflow bundle must carry a non-empty settings object")
    workflow_file = bundle.get("workflow_file")
    if not isinstance(workflow_file, str) or not workflow_file:
        return fail(
            "workflow_file_missing",
            "workflow bundle must carry a ComfyUI-restorable workflow_file",
        )
    if bundle.get("source_traceable") is not True:
        return fail(
            "source_not_traceable",
            "workflow bundle source must be traceable",
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
    report = check_freevideo_workflow_bundle(params.get("bundle"))
    report_path = out_dir / "freevideo_workflow_bundle_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_workflow_bundle_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_workflow_bundle_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "bundle": {"type": "object"},
                },
                "required": ["bundle"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "FreeVideo workflow bundle gate: prompt, seed, and "
                "settings travel with the video, a ComfyUI-restorable "
                "workflow file is present, and the source is traceable."
            ),
        )
    )
    return ["qa.freevideo_workflow_bundle_gate"]


__all__ = [
    "check_freevideo_workflow_bundle",
    "register_freevideo_workflow_bundle_gate_capabilities_once",
]
