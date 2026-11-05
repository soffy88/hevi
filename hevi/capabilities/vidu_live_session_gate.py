"""Vidu live component-session gate (``qa.vidu_live_session_gate``).

Clean-room restatement of the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): the upstream live system drives
its digital human through a cloud Vidu s2 component session
(``s_avatar/component``), the avatar given by ``avatar_id`` or
``image_uri`` and actions taken from an action library, over an
RTC channel in managed or customer mode. Nothing is rendered
locally. This gate judges claims about such a session only: an
asynchronous reference-to-video job must never be claimed to be
a live session, a claim that rendering is local fails, a claim
that the run is free fails (the code is free, running is not),
and any cost or balance figure must declare its source. Keys
never enter a claim: a claim that embeds key material fails,
and every claim must declare that a Vidu key is required. This
gate executes nothing: ``executed_here`` is always false, and a
real live session is a separate key/GPU/real-machine case.
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

MODEL_ID = "vidu-s2"
SESSION_KIND = "component"
RTC_MODES: frozenset[str] = frozenset({"managed", "customer"})
AVATAR_KINDS: frozenset[str] = frozenset({"avatar_id", "image_uri"})
COST_SOURCES: frozenset[str] = frozenset({"unverified_readme", "platform_console"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vidu_live_session(claim: Any) -> dict[str, Any]:
    """Validate a claim about a Vidu live component session.

    Verdicts are ``pass`` / ``fail`` only. The session kind must
    be the component session, the model must be vidu-s2, the RTC
    mode must be managed or customer, cloud rendering must be
    declared, a Vidu key must be declared required and no key
    material may be embedded, the run must not be claimed free,
    and any cost or balance figure must declare its source.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "model": MODEL_ID,
            "session_kind": None,
            "rtc_mode": None,
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail(
            "claim_not_object",
            "vidu live session claim must be a JSON object",
        )
    session_kind = claim.get("session_kind")
    if session_kind != SESSION_KIND:
        return fail(
            "session_kind_not_component",
            "a Vidu live session is the s_avatar/component session; "
            "an asynchronous reference-to-video job is not a live session",
        )
    model = claim.get("model")
    if model != MODEL_ID:
        return fail(
            "model_mismatch",
            "this gate judges vidu-s2 component sessions only",
        )
    rtc_mode = claim.get("rtc_mode")
    if rtc_mode not in RTC_MODES:
        return fail(
            "rtc_mode_missing",
            "rtc mode must be managed or customer, one of the two",
        )
    if claim.get("local_rendered") is True:
        return fail(
            "local_render_claimed",
            "the Vidu live session renders in the cloud; it cannot be claimed local",
        )
    if claim.get("declares_cloud_rendered") is not True:
        return fail(
            "cloud_render_not_declared",
            "claim must declare that rendering happens in the cloud",
        )
    if claim.get("declares_key_required") is not True:
        return fail(
            "key_required_not_declared",
            "claim must declare that a Vidu key is required (separate case)",
        )
    if claim.get("key_material_present") is True:
        return fail(
            "key_material_embedded",
            "keys never enter a claim; key material must not be embedded",
        )
    if claim.get("claims_free") is True:
        return fail(
            "free_run_claimed",
            "the code is free, running is not; the run cannot be claimed free",
        )
    if claim.get("cost_per_second") is not None and claim.get("cost_source") not in COST_SOURCES:
        return fail(
            "cost_source_missing",
            "a cost figure must declare its source (unverified_readme or platform_console)",
        )
    if (
        claim.get("minimum_balance_credits") is not None
        and claim.get("declares_balance_unverified") is not True
    ):
        return fail(
            "balance_not_declared_unverified",
            "a minimum-balance figure is a README self-report and must be declared unverified",
        )
    avatar = claim.get("avatar")
    if avatar is not None:
        if not isinstance(avatar, dict) or avatar.get("kind") not in AVATAR_KINDS:
            return fail(
                "avatar_kind_invalid",
                "avatar must be given by avatar_id or image_uri",
            )
        if not isinstance(avatar.get("value"), str) or not avatar["value"].strip():
            return fail(
                "avatar_value_missing",
                "avatar needs a non-empty avatar_id or image_uri value",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "model": MODEL_ID,
        "session_kind": SESSION_KIND,
        "rtc_mode": rtc_mode,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_vidu_live_session(params.get("claim"))
    report_path = out_dir / "vidu_live_session_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vidu_live_session_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vidu_live_session_gate",
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
                "Vidu live component-session gate: only the cloud "
                "vidu-s2 s_avatar/component session counts as live; "
                "async reference-to-video, local rendering, free-run "
                "and key-embedding claims fail."
            ),
        )
    )
    return ["qa.vidu_live_session_gate"]


__all__ = [
    "AVATAR_KINDS",
    "COST_SOURCES",
    "MODEL_ID",
    "RTC_MODES",
    "SESSION_KIND",
    "check_vidu_live_session",
    "register_vidu_live_session_gate_capabilities_once",
]
