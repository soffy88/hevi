"""OmniVoice live wiring note (``qa.omnivoice_live_wire_note``).

Clean-room restatement of the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): the upstream live system
speaks only through an OmniVoice service, a Gradio service on
port 9877 with GPU, whose live wiring warms up hot voices,
collects cache garbage and watches video memory. The weights
(about 10GB) live outside the repository and are never part of
it. Cloning inside that service is a clone equivalent: the
upstream repository carries no consent or authorization check,
so any clone request here goes through hevi's existing clone
hard intercept and passes only with an own-or-licensed
authorization declaration naming the voice and its evidence.
This gate executes nothing and starts no service:
``executed_here`` is always false, and a real service is a
separate GPU/weights case.
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

SERVICE_PORT = 9877
SERVICE_KIND = "gradio"
SAMPLE_RATE_HZ = 24000

_CLONE_MARKERS: frozenset[str] = frozenset(
    {"clone", "clone_voice", "voice_clone", "zero_shot_clone", "zero-shot-clone"}
)
_REFERENCE_AUDIO_SOURCES: frozenset[str] = frozenset(
    {"reference_audio", "voice_ref", "audio_file", "reference-clip"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _find_clone_markers(node: Any, path: str, found: list[str]) -> None:
    """Collect paths where a voice-clone request hides in a claim."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in _CLONE_MARKERS:
                found.append(child)
            if key == "kind" and value in _CLONE_MARKERS:
                found.append(child)
            if key == "cloned" and value is True:
                found.append(child)
            if key == "source" and value in _REFERENCE_AUDIO_SOURCES:
                found.append(child)
            _find_clone_markers(value, child, found)
    elif isinstance(node, list):
        for position, value in enumerate(node):
            _find_clone_markers(value, f"{path}[{position}]", found)


def _authorization_ok(auth: Any) -> bool:
    if not isinstance(auth, dict):
        return False
    voice_id = auth.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        return False
    if auth.get("authorization_kind") not in ("own", "licensed"):
        return False
    evidence = auth.get("evidence_ref")
    return isinstance(evidence, str) and bool(evidence.strip())


def check_omnivoice_live_wire(claim: Any) -> dict[str, Any]:
    """Validate a claim about OmniVoice live wiring.

    Verdicts are ``pass`` / ``fail`` only. The claim must declare
    the Gradio service on port 9877, GPU required, hot-voice
    warmup, cache garbage collection and a video-memory
    watchdog; weights must not be claimed included. Any clone
    request is hard-intercepted unless an own-or-licensed voice
    authorization declaration is present.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "service_port": None,
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail(
            "claim_not_object",
            "omnivoice live wiring claim must be a JSON object",
        )
    if claim.get("service_kind") != SERVICE_KIND:
        return fail(
            "service_kind_mismatch",
            "OmniVoice live wiring is a Gradio service",
        )
    if claim.get("service_port") != SERVICE_PORT:
        return fail(
            "service_port_mismatch",
            "OmniVoice live wiring runs on port 9877",
        )
    if claim.get("gpu_required") is not True:
        return fail(
            "gpu_required_not_declared",
            "OmniVoice live wiring needs a GPU; it must be declared",
        )
    if claim.get("hot_voice_warmup") is not True:
        return fail(
            "hot_voice_warmup_missing",
            "live wiring must declare hot-voice warmup",
        )
    if claim.get("cache_gc") is not True:
        return fail(
            "cache_gc_missing",
            "live wiring must declare cache garbage collection",
        )
    if claim.get("vram_watchdog") is not True:
        return fail(
            "vram_watchdog_missing",
            "live wiring must declare a video-memory watchdog",
        )
    if claim.get("weights_included") is True:
        return fail(
            "weights_claimed_included",
            "OmniVoice weights live outside the repository and cannot be claimed included",
        )
    sample_rate = claim.get("sample_rate_hz")
    if sample_rate is not None and sample_rate != SAMPLE_RATE_HZ:
        return fail(
            "sample_rate_mismatch",
            "OmniVoice live output is 24000 Hz",
        )
    markers: list[str] = []
    _find_clone_markers(claim, "", markers)
    if markers and not _authorization_ok(claim.get("voice_authorization")):
        return fail(
            "clone_blocked",
            "voice cloning is hard-intercepted; a clone request "
            "needs an own-or-licensed voice authorization "
            "declaration (voice id, kind, evidence reference)",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "service_port": SERVICE_PORT,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_omnivoice_live_wire(params.get("claim"))
    report_path = out_dir / "omnivoice_live_wire_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_omnivoice_live_wire_note_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.omnivoice_live_wire_note",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claim": {"type": "object"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "OmniVoice live wiring note: Gradio service on port "
                "9877 with GPU, hot-voice warmup, cache garbage "
                "collection and a video-memory watchdog; weights are "
                "separate; clone requests go through the hard "
                "intercept."
            ),
        )
    )
    return ["qa.omnivoice_live_wire_note"]


__all__ = [
    "SAMPLE_RATE_HZ",
    "SERVICE_KIND",
    "SERVICE_PORT",
    "check_omnivoice_live_wire",
    "register_omnivoice_live_wire_note_capabilities_once",
]
