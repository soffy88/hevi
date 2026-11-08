"""VibeVoice voice-prompt authorization gate (``qa.vibevoice_voice_prompt_authorization_gate``).

Clean-room restatement of the VibeVoice review (see
``VIBEVOICE_ATTRIBUTION.md``): VibeVoice-TTS-1.5B fixes the
voice from a voice-prompt audio clip, which is functionally
equivalent to zero-shot voice cloning, and the upstream
repository carries no consent or authorization check of any
kind -- only a deepfake warning and a research-only notice.
Inside hevi the same shape already exists: the local
vibevoice worker takes a per-line ``voice_ref``. This gate
routes every reference-audio voice prompt through the
existing clone hard intercept: only the speaker's own voice
or a licensed voice, declared with evidence, passes. Any
clone request fails outright. This gate judges plans only:
it synthesizes no audio and handles no voice data of any kind.
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

_AUTHORIZATION_KINDS: tuple[str, str] = ("own", "licensed")

_CLONE_MARKERS: frozenset[str] = frozenset(
    {"clone", "clone_voice", "voice_clone", "zero_shot_clone", "zero-shot-clone"}
)

# A voice prompt whose source is reference audio is a clone
# equivalent and needs an authorization declaration.
_REFERENCE_AUDIO_SOURCES: frozenset[str] = frozenset(
    {"reference_audio", "voice_ref", "audio_file", "reference-clip"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _find_clone_markers(node: Any, path: str, found: list[str]) -> None:
    """Collect paths where a voice-clone request hides in a plan."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in _CLONE_MARKERS:
                found.append(child)
            if key == "kind" and value in _CLONE_MARKERS:
                found.append(child)
            if key == "cloned" and value is True:
                found.append(child)
            _find_clone_markers(value, child, found)
    elif isinstance(node, list):
        for position, value in enumerate(node):
            _find_clone_markers(value, f"{path}[{position}]", found)


def _authorization_ok(auth: Any) -> tuple[bool, str | None]:
    """Return (ok, voice_id) for a voice authorization declaration."""
    if not isinstance(auth, dict):
        return False, None
    voice_id = auth.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        return False, None
    if auth.get("authorization_kind") not in _AUTHORIZATION_KINDS:
        return False, None
    evidence = auth.get("evidence_ref")
    if not isinstance(evidence, str) or not evidence.strip():
        return False, None
    return True, voice_id


def check_vibevoice_voice_prompt_authorization(plan: Any) -> dict[str, Any]:
    """Validate a VibeVoice narration plan's voice-prompt use.

    Verdicts are ``pass`` / ``fail`` only. Any clone request
    fails outright. A reference-audio voice prompt (including
    a per-line ``voice_ref``) passes only with a voice
    authorization declaration: a voice id, an authorization
    kind of ``own`` or ``licensed``, and an evidence
    reference. Embedded-speaker and stock-voice plans, which
    carry no reference audio, pass this gate (speaker
    identity itself is judged by
    ``qa.vibevoice_realtime_speaker_gate``).
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "voice_id": None,
            "clone_route": "never_connected",
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail(
            "plan_not_object",
            "vibevoice voice-prompt plan must be a JSON object",
        )
    markers: list[str] = []
    _find_clone_markers(plan, "", markers)
    if markers:
        return fail(
            "clone_blocked",
            f"voice cloning is never available; clone request intercepted at {markers[0]}",
        )
    if plan.get("clone") is True or plan.get("clone_voice") is True:
        return fail(
            "clone_blocked",
            "voice cloning is never available; clone requests fail",
        )

    needs_authorization = False
    prompt = plan.get("voice_prompt")
    if isinstance(prompt, dict):
        source = prompt.get("source")
        if source in _REFERENCE_AUDIO_SOURCES:
            needs_authorization = True
        elif source not in (None, "embedded", "stock"):
            return fail(
                "voice_prompt_source_unknown",
                "voice prompt source must be embedded, stock, or reference audio",
            )
    script = plan.get("script")
    if isinstance(script, list):
        for line in script:
            if isinstance(line, dict):
                ref = line.get("voice_ref")
                if isinstance(ref, str) and ref.strip():
                    needs_authorization = True
    if not needs_authorization:
        return {
            "verdict": "pass",
            "ok": True,
            "issues": [],
            "voice_id": None,
            "clone_route": "never_connected",
            "executed_here": False,
        }
    ok, voice_id = _authorization_ok(plan.get("voice_authorization"))
    if not ok:
        return fail(
            "voice_prompt_authorization_missing",
            "a reference-audio voice prompt needs a voice "
            "authorization declaration (voice id, own or licensed "
            "kind, evidence reference)",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "voice_id": voice_id,
        "clone_route": "never_connected",
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_vibevoice_voice_prompt_authorization(params.get("plan"))
    report_path = out_dir / "vibevoice_voice_prompt_authorization_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vibevoice_voice_prompt_authorization_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vibevoice_voice_prompt_authorization_gate",
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
                "VibeVoice voice-prompt authorization gate: a "
                "reference-audio voice prompt is a clone equivalent "
                "and passes only with an own/licensed voice "
                "authorization; any clone request is refused outright."
            ),
        )
    )
    return ["qa.vibevoice_voice_prompt_authorization_gate"]


__all__ = [
    "check_vibevoice_voice_prompt_authorization",
    "register_vibevoice_voice_prompt_authorization_gate_capabilities_once",
]
