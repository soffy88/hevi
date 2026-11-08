"""Story text probe gate (``qa.story_text_probe_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): before any
picture is drawn, the story is probed in plain text. Three
questions must be answered — what is the memory hook, why
would anyone stay, and what makes this one unlike the
others. The probe only advises; it never blocks. Any probe
that claims to be a gate fails. This gate judges the probe
record only. It renders nothing: ``executed_here`` is always
false.
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

# The three questions a text probe must answer.
PROBE_QUESTIONS: tuple[str, ...] = (
    "memory_hook",
    "retention_reason",
    "uniqueness",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_story_text_probe(probe: Any) -> dict[str, Any]:
    """Validate a story text probe record.

    Pass requires all three probe questions answered and the
    probe declared advisory only. A probe that claims to
    block fails: a text probe advises, it never gates.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(probe, dict):
        return fail("probe_not_object", "probe must be a JSON object")
    for question in PROBE_QUESTIONS:
        if not probe.get(question):
            return fail(
                "probe_incomplete",
                f"text probe is missing an answer to {question}; memory hook, retention reason and uniqueness must all be answered",
            )
    binding = probe.get("binding")
    if binding is True or binding == "blocking":
        return fail(
            "probe_claimed_binding",
            "a text probe only advises; it never blocks and is never a gate",
        )
    if binding not in (False, "advisory"):
        return fail(
            "probe_binding_unclear",
            "probe must declare itself advisory only",
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
    report = check_story_text_probe(params.get("probe"))
    report_path = out_dir / "story_text_probe_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_story_text_probe_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.story_text_probe_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "probe": {"type": "object"},
                },
                "required": ["probe"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Story text probe gate: plain-text probe answering "
                "memory hook, retention reason and uniqueness; "
                "advisory only, never a gate."
            ),
        )
    )
    return ["qa.story_text_probe_gate"]


__all__ = [
    "PROBE_QUESTIONS",
    "check_story_text_probe",
    "register_story_text_probe_gate_capabilities_once",
]
