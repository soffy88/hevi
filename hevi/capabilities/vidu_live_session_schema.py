"""Vidu live session schema (``video.vidu_live_session_schema``).

Fake-level contract for a Vidu live component session of the
kind described in the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): cloud vidu-s2
``s_avatar/component`` session, avatar by ``avatar_id`` or
``image_uri``, actions from an action library, RTC channel in
managed or customer mode, optional server-side recording. The
contract certifies the shape of the plan only. It starts no
session, sends no request and holds no key: any key material
in the plan is refused, and any claim that a session started
here fails outright. Every compiled contract declares
``executed_here: false``. Whether a live session actually runs
is a question for a real key/GPU/real-machine case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
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
_KEY_FIELDS: frozenset[str] = frozenset(
    {"api_key", "vidu_key", "key", "token", "secret", "access_key"}
)


def _find_key_fields(node: Any, path: str, found: list[str]) -> None:
    """Collect paths where key material hides in a plan."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in _KEY_FIELDS and isinstance(value, str) and value.strip():
                found.append(child)
            _find_key_fields(value, child, found)
    elif isinstance(node, list):
        for position, value in enumerate(node):
            _find_key_fields(value, f"{path}[{position}]", found)


def compile_vidu_live_session(plan: Any) -> dict[str, Any]:
    """Compile one Vidu live component-session contract.

    ``plan`` carries ``model``, ``session_kind``, ``avatar``
    (``kind`` avatar_id/image_uri plus a non-empty value),
    ``actions`` (a list of ``{library_id}`` entries, 0 being the
    platform default library) and ``rtc`` (``mode`` managed or
    customer, optional ``recording``). Raises
    :class:`CapabilityError` on any shape violation, on any key
    material, or on any claim that a session started here. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("vidu live session plan must be an object")
    if plan.get("model") != MODEL_ID:
        raise CapabilityError("vidu live session contract is for vidu-s2 only")
    if plan.get("session_kind") != SESSION_KIND:
        raise CapabilityError(
            "vidu live session contract covers the s_avatar/component session only"
        )
    if plan.get("executed_here") is True or plan.get("live_started") is True:
        raise CapabilityError("live session claims are refused here; this contract starts nothing")
    key_fields: list[str] = []
    _find_key_fields(plan, "", key_fields)
    if key_fields:
        raise CapabilityError(
            f"keys never enter the contract; key material refused at {key_fields[0]}"
        )
    avatar = plan.get("avatar")
    if not isinstance(avatar, dict):
        raise CapabilityError("vidu live session plan requires an avatar object")
    if avatar.get("kind") not in AVATAR_KINDS:
        raise CapabilityError("avatar must be given by avatar_id or image_uri")
    if not isinstance(avatar.get("value"), str) or not avatar["value"].strip():
        raise CapabilityError("avatar needs a non-empty avatar_id or image_uri value")
    actions = plan.get("actions")
    if not isinstance(actions, list):
        raise CapabilityError("vidu live session plan requires an actions list")
    for position, action in enumerate(actions):
        if not isinstance(action, dict):
            raise CapabilityError(f"action {position} must be an object")
        library_id = action.get("library_id")
        if not isinstance(library_id, int) or isinstance(library_id, bool) or library_id < 0:
            raise CapabilityError(
                f"action {position} needs a library_id integer >= 0 "
                "(0 is the platform default library)"
            )
    rtc = plan.get("rtc")
    if not isinstance(rtc, dict):
        raise CapabilityError("vidu live session plan requires an rtc object")
    if rtc.get("mode") not in RTC_MODES:
        raise CapabilityError("rtc mode must be managed or customer, one of the two")
    recording = rtc.get("recording")
    if recording is not None and not isinstance(recording, bool):
        raise CapabilityError("rtc recording must be a boolean when present")
    return {
        "contract": "vidu-live-session",
        "model": MODEL_ID,
        "session_kind": SESSION_KIND,
        "avatar_kind": avatar["kind"],
        "actions": len(actions),
        "rtc_mode": rtc["mode"],
        "recording": bool(recording),
        "executed_here": False,
        "live_started": False,
        "key_case": "separate_key_gpu_case",
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_vidu_live_session(params.get("plan"))
    report_path = out_dir / "vidu_live_session_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "rtc_mode": report["rtc_mode"],
            "executed_here": False,
        },
    )


def register_vidu_live_session_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.vidu_live_session_schema",
            kind="video",
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
            layer="obase",
            description=(
                "Vidu live session schema (fake): cloud vidu-s2 "
                "s_avatar/component session, avatar by avatar_id or "
                "image_uri, action library ids, managed/customer RTC; "
                "no session starts here and no key enters the contract."
            ),
        )
    )
    return ["video.vidu_live_session_schema"]


__all__ = [
    "AVATAR_KINDS",
    "MODEL_ID",
    "RTC_MODES",
    "SESSION_KIND",
    "compile_vidu_live_session",
    "register_vidu_live_session_schema_capabilities_once",
]
