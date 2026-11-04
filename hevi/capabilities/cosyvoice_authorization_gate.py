"""CosyVoice voice-authorization gate (``qa.cosyvoice_authorization_gate``).

Hard-intercept gate for any CosyVoice narration plan. A plan
passes only when it declares a voice authorization: a voice id,
an authorization kind of ``own`` or ``licensed``, and an
evidence reference. A plan with no authorization claim fails.
Any voice-clone request fails, always: the clone route is
never connected, and no clone, zero-shot clone, or training
route exists in hevi. Attribution is checked against the same
record as ``qa.cosyvoice_attribution_note``: code is cited as
``QwenAudio/CosyVoice``, models under the ``FunAudioLLM``
namespace, never mixed. Claims that CosyVoice is installed or
actively maintained fail against the recorded standing
(maintenance slowed, last observed push 2026-05-25). This
gate judges plans only and executes nothing:
``executed_here`` is always false, and real inference is a
separate GPU/real-machine case. See
OPEN_SKILLS_ATTRIBUTION.md and FIFTEEN_TOOLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.cosyvoice_attribution_note import (
    CODE_REPO,
    MODEL_NAMESPACE,
    OLD_CODE_ADDRESS,
)
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_AUTHORIZATION_KINDS: tuple[str, str] = ("own", "licensed")

# Any of these, anywhere in the plan's request fields, is a
# clone request and is refused outright.
_CLONE_MARKERS: frozenset[str] = frozenset(
    {"clone", "voice_clone", "zero_shot_clone", "zero-shot-clone"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _looks_like_clone(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in _CLONE_MARKERS
    if isinstance(value, dict):
        return any(
            _looks_like_clone(item) for item in value.values()
        ) or any(
            isinstance(key, str) and key.lower() in _CLONE_MARKERS
            and value[key] is True
            for key in value
        )
    if isinstance(value, list):
        return any(_looks_like_clone(item) for item in value)
    return False


def check_cosyvoice_authorization(plan: Any) -> dict[str, Any]:
    """Validate a CosyVoice narration plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Missing voice
    authorization, any clone request, misattributed code/model
    references, and false installed/maintained claims all fail.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": issues + [_issue(code, detail)],
            "voice_id": None,
            "clone_route": "never_connected",
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail(
            "plan_not_object", "cosyvoice plan must be a JSON object"
        )
    if plan.get("clone") is True or plan.get("clone_voice") is True:
        return fail(
            "clone_route_refused",
            "voice cloning is never connected; clone requests fail",
        )
    request_kind = plan.get("request_kind")
    mode = plan.get("mode")
    if _looks_like_clone(request_kind) or _looks_like_clone(mode):
        return fail(
            "clone_route_refused",
            "voice cloning is never connected; clone requests fail",
        )
    auth = plan.get("voice_authorization")
    voice_id: str | None = None
    if not isinstance(auth, dict):
        return fail(
            "voice_authorization_missing",
            "a voice authorization declaration (voice id, own or "
            "licensed kind, evidence reference) is required",
        )
    voice_id = auth.get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        return fail(
            "voice_authorization_missing",
            "voice authorization must name a voice id",
        )
    kind = auth.get("authorization_kind")
    if kind in _CLONE_MARKERS:
        return fail(
            "clone_route_refused",
            "voice cloning is never connected; clone requests fail",
        )
    if kind not in _AUTHORIZATION_KINDS:
        issues.append(
            _issue(
                "voice_authorization_missing",
                "authorization_kind must be 'own' or 'licensed'",
            )
        )
    evidence = auth.get("evidence_ref")
    if not isinstance(evidence, str) or not evidence.strip():
        issues.append(
            _issue(
                "voice_authorization_missing",
                "voice authorization must carry an evidence reference",
            )
        )
    code_ref = plan.get("code_ref")
    if code_ref is not None and code_ref != CODE_REPO:
        issues.append(
            _issue(
                "code_ref_misattributed",
                f"code repository must be cited as {CODE_REPO}; "
                f"the old address {OLD_CODE_ADDRESS} is a redirect, "
                "not the canonical name",
            )
        )
    model_ref = plan.get("model_ref")
    if model_ref is not None and not str(model_ref).startswith(
        MODEL_NAMESPACE + "/"
    ):
        issues.append(
            _issue(
                "model_ref_misattributed",
                "model releases publish under the FunAudioLLM "
                "namespace; do not rename a model release under "
                "the code repository's organization",
            )
        )
    claims = plan.get("claims")
    if isinstance(claims, dict):
        if claims.get("installed") is True:
            issues.append(
                _issue(
                    "installed_claim_refused",
                    "CosyVoice is not installed or wired in hevi",
                )
            )
        if claims.get("actively_maintained") is True:
            issues.append(
                _issue(
                    "maintenance_claim_refused",
                    "maintenance is recorded as slowed (last "
                    "observed push 2026-05-25)",
                )
            )
    if plan.get("executed_here") is True:
        issues.append(
            _issue(
                "execution_claim_refused",
                "this gate executes nothing; executed_here stays false",
            )
        )
    if issues:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": issues,
            "voice_id": voice_id,
            "clone_route": "never_connected",
            "executed_here": False,
        }
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "voice_id": voice_id,
        "clone_route": "never_connected",
        "executed_here": False,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_cosyvoice_authorization(params.get("plan"))
    report_path = out_dir / "cosyvoice_authorization_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_cosyvoice_authorization_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.cosyvoice_authorization_gate",
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
                "CosyVoice voice-authorization gate: no voice "
                "authorization claim means fail, and any clone "
                "request is refused outright; the clone route is "
                "never connected."
            ),
        )
    )
    return ["qa.cosyvoice_authorization_gate"]


__all__ = [
    "check_cosyvoice_authorization",
    "register_cosyvoice_authorization_gate_capabilities_once",
]
