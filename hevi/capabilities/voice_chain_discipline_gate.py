"""Voice chain discipline gate (``qa.voice_chain_discipline_gate``).

Clean-room restatement of the voice-chain discipline recorded
in the Infinite Creation delta2 review (see
``INFINITE_CREATION_ATTRIBUTION.md``): a voice plan may use
stock voices, authorized custom voices, and regenerated
readings, but voice cloning is never an available route -- any
request for it is intercepted here, unconditionally, because
the reviewed project's clone path carries no consent or
authorization check. Regenerated readings must declare the
fallback narration text they fall back to, and an authorized
custom voice must declare its authorization. This gate judges
voice plans only: it synthesizes no audio and handles no voice
data of any kind.
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

_KINDS = ("stock", "authorized_custom", "regeneration", "narration")
_CLONE_KEYS = ("clone_voice", "voice_clone")
_CLONE_KINDS = ("clone", "clone_voice", "voice_clone")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.voice_chain_discipline_gate: {detail}"}
    issue.update(extra)
    return issue


def _find_clone_markers(node: Any, path: str, found: list[str]) -> None:
    """Collect paths where a voice-clone request hides in a plan."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in _CLONE_KEYS:
                found.append(child)
            if key == "kind" and value in _CLONE_KINDS:
                found.append(child)
            if key == "cloned" and value is True:
                found.append(child)
            _find_clone_markers(value, child, found)
    elif isinstance(node, list):
        for position, value in enumerate(node):
            _find_clone_markers(value, f"{path}[{position}]", found)


def check_voice_chain_discipline(plan: Any) -> dict[str, Any]:
    """Judge one voice chain plan.

    ``plan`` carries ``voice_requests`` (each with ``kind`` and,
    depending on kind, ``authorization`` or
    ``fallback_narration``). Verdict ``pass`` means no clone
    request appears anywhere in the plan, every authorized
    custom voice declares its authorization, and every
    regenerated reading declares its fallback narration text.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("voice chain plan must be an object")
    issues: list[dict[str, Any]] = []
    markers: list[str] = []
    _find_clone_markers(plan, "", markers)
    issues.extend(
        _issue(
            "clone_blocked",
            f"voice cloning is never available; clone request intercepted at {marker}",
        )
        for marker in markers
    )
    requests = plan.get("voice_requests")
    if not isinstance(requests, list) or not requests:
        raise CapabilityError("voice chain plan requires a non-empty voice_requests list")
    for position, request in enumerate(requests):
        if not isinstance(request, dict):
            issues.append(
                _issue("request_not_object", f"voice request {position} is not an object")
            )
            continue
        kind = request.get("kind")
        if kind not in _KINDS:
            issues.append(
                _issue(
                    "kind_invalid",
                    f"voice request {position} kind must be one of {_KINDS}",
                    request=position,
                )
            )
            continue
        if kind == "authorized_custom" and (
            not isinstance(request.get("authorization"), str)
            or not request["authorization"].strip()
        ):
            issues.append(
                _issue(
                    "authorization_missing",
                    f"voice request {position} (authorized_custom) requires an authorization declaration",
                    request=position,
                )
            )
        if kind == "regeneration" and (
            not isinstance(request.get("fallback_narration"), str)
            or not request["fallback_narration"].strip()
        ):
            issues.append(
                _issue(
                    "fallback_missing",
                    f"voice request {position} (regeneration) requires fallback_narration text",
                    request=position,
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": ["voice output quality is unverified; no audio was generated here"],
        "request_count": len(requests),
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_voice_chain_discipline(params.get("plan"))
    report_path = out_dir / "voice_chain_discipline.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_voice_chain_discipline_gate_capabilities_once() -> list[str]:
    """Register ``qa.voice_chain_discipline_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.voice_chain_discipline_gate",
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
            description=(
                "Voice chain discipline gate: voice cloning is hard "
                "intercepted everywhere in a plan, authorized custom "
                "voices must declare authorization, and regenerated "
                "readings must declare fallback narration text."
            ),
        )
    )
    return ["qa.voice_chain_discipline_gate"]


__all__ = [
    "check_voice_chain_discipline",
    "register_voice_chain_discipline_gate_capabilities_once",
]
