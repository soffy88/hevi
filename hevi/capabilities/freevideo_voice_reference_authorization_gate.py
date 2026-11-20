"""Voice reference authorization gate (``qa.freevideo_voice_reference_authorization_gate``).

FreeVideo dubbing drives a voice from a timbre reference:
a zero-second-clone equivalent. Upstream carries no
authorization or consent check, so hevi must supply its
own. In the reviewer's own words, a dubbing plan fails when
it asks for cloning, when it carries no voice reference,
when the reference has no voice id, or when the
authorization is not the speaker's own voice or an
authorized voice with proof. Only authorized voices ever
speak here, on the same terms as the existing CosyVoice
authorization gate (clone route never connected).

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here. This gate judges dubbing plans only; it never records,
clones, or synthesizes a voice.
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

AUTHORIZATION_KINDS: frozenset[str] = frozenset({"own", "authorized"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_freevideo_voice_reference(plan: Any) -> dict[str, Any]:
    """Validate a FreeVideo-style dubbing voice reference.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    it is not an object, when it asks for cloning, when it
    carries no voice reference, when the reference has no
    voice id, when the authorization is missing, when the
    authorization kind is neither the speaker's own voice
    nor an authorized voice, or when the authorization proof
    is empty.
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
        return fail("plan_not_object", "dubbing plan must be a JSON object")
    if plan.get("clone") is True or plan.get("clone_voice") is True:
        return fail(
            "clone_route_refused",
            "voice cloning is never connected; clone requests fail",
        )
    reference = plan.get("voice_reference")
    if not isinstance(reference, dict):
        return fail(
            "voice_reference_missing",
            "dubbing needs a declared voice reference; none was given",
        )
    voice_id = reference.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id:
        return fail("voice_id_missing", "voice reference must carry a voice_id")
    authorization = reference.get("authorization")
    if not isinstance(authorization, dict):
        return fail(
            "voice_authorization_missing",
            f"voice {voice_id!r} needs an authorization declaration",
        )
    kind = authorization.get("kind")
    if kind not in AUTHORIZATION_KINDS:
        return fail(
            "voice_authorization_kind_invalid",
            f"authorization kind must be 'own' or 'authorized', got {kind!r}",
        )
    proof = authorization.get("proof")
    if not isinstance(proof, str) or not proof:
        return fail(
            "voice_authorization_proof_missing",
            f"voice {voice_id!r} needs a non-empty authorization proof",
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
    report = check_freevideo_voice_reference(params.get("plan"))
    report_path = out_dir / "freevideo_voice_reference_authorization_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_voice_reference_authorization_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_voice_reference_authorization_gate",
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
                "FreeVideo voice reference authorization gate: "
                "dubbing voice references are zero-second-clone "
                "equivalents, so only the speaker's own voice or an "
                "authorized voice with proof may speak; clone "
                "requests always fail."
            ),
        )
    )
    return ["qa.freevideo_voice_reference_authorization_gate"]


__all__ = [
    "AUTHORIZATION_KINDS",
    "check_freevideo_voice_reference",
    "register_freevideo_voice_reference_authorization_gate_capabilities_once",
]
