"""Authorised-portrait gate (``qa.portrait_consent_gate``).

Clean-room method intake, written from the method description only.
This is a gate, not a generator: it decides whether a portrait may
be used for a stated purpose, and it never generates a digital
human, never picks a supplier, and never touches a key.

Method:
* A portrait record carries a consent status (authorised, pending,
  denied, unknown), a scope list of permitted uses, and an optional
  expiry date. The gate is fail-closed: anything that is not an
  explicit, in-scope, unexpired authorisation is not allowed.
* Expiry is only evaluated when the caller supplies ``as_of_date``.
  Without it, an expiring record cannot be proven current, so it
  goes to pending with reason expiry_not_checked -- the gate does
  not guess the date.
* An unknown portrait id is refused, not treated as pending
  authorisation: there is no record to authorise it.
* When the verdict is anything other than allowed, the style list
  is empty. Styles are generic descriptors (for example
  documentary_interview), never supplier names, and no supplier
  field exists anywhere in the output.
* Keys are refused at the door: any request carrying a key-like
  field (api_key, provider key, token, secret) raises, so a key
  can never be smuggled through this gate.

Failure contract: a malformed registry, a duplicate portrait id,
an unknown consent status, an unparseable date, a missing
intended use, or any key-like field in the request all raise
CapabilityError. An unknown portrait id is a refused verdict,
not an exception, because refusing is the gate's job.
"""

from __future__ import annotations

import json
from datetime import date
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
_CONSENTS = ("authorized", "pending", "denied", "unknown")
_KEY_FIELDS = ("api_key", "apikey", "provider_key", "token", "secret", "password", "key")
_STYLES = (
    {"id": "documentary_interview", "description": "Seated interview framing, neutral background"},
    {"id": "studio_portrait", "description": "Studio portrait framing, plain background"},
    {"id": "on_location_profile", "description": "On-location profile framing, real setting"},
)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"qa.portrait_consent_gate: {what} must be a non-empty string")
    return value.strip()


def _parse_date(text: Any, what: str) -> date:
    if not isinstance(text, str):
        raise CapabilityError(f"qa.portrait_consent_gate: {what} must be an ISO date YYYY-MM-DD")
    try:
        parts = text.strip().split("-")
        if len(parts) != 3:
            raise ValueError("not a date")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError) as exc:
        raise CapabilityError(f"qa.portrait_consent_gate: {what} is not a parseable ISO date") from exc


def gate_portrait(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise CapabilityError("qa.portrait_consent_gate: request must be a JSON object")
    for field in _KEY_FIELDS:
        if field in request:
            raise CapabilityError("qa.portrait_consent_gate: key-like fields are not accepted by this gate")
    registry_raw = request.get("registry")
    if not isinstance(registry_raw, dict):
        raise CapabilityError("qa.portrait_consent_gate: registry must be a JSON object")
    portraits_raw = registry_raw.get("portraits")
    if not isinstance(portraits_raw, list) or not portraits_raw:
        raise CapabilityError("qa.portrait_consent_gate: registry.portraits must be a non-empty list")
    portraits: dict[str, dict[str, Any]] = {}
    for i, p in enumerate(portraits_raw):
        if not isinstance(p, dict):
            raise CapabilityError(f"qa.portrait_consent_gate: portrait {i} must be a JSON object")
        for field in _KEY_FIELDS:
            if field in p:
                raise CapabilityError("qa.portrait_consent_gate: key-like fields are not accepted by this gate")
        pid = _require_str(p.get("portrait_id"), f"portrait {i}.portrait_id")
        if pid in portraits:
            raise CapabilityError(f"qa.portrait_consent_gate: duplicate portrait id {pid!r}")
        consent = p.get("consent")
        if consent not in _CONSENTS:
            raise CapabilityError(f"qa.portrait_consent_gate: portrait {pid!r} unknown consent {consent!r}")
        scope = p.get("scope", [])
        if not isinstance(scope, list) or not all(isinstance(s, str) for s in scope):
            raise CapabilityError(f"qa.portrait_consent_gate: portrait {pid!r} scope must be a list of strings")
        expires = p.get("expires_at")
        expires_parsed = _parse_date(expires, f"portrait {pid!r}.expires_at") if expires is not None else None
        portraits[pid] = {
            "portrait_id": pid, "consent": consent, "scope": list(scope),
            "expires_at": expires, "expires_parsed": expires_parsed,
        }
    pid = _require_str(request.get("portrait_id"), "portrait_id")
    use = _require_str(request.get("intended_use"), "intended_use")
    style = request.get("style")
    if style is not None and style not in [s["id"] for s in _STYLES]:
        raise CapabilityError(f"qa.portrait_consent_gate: unknown style {style!r}")
    as_of_raw = request.get("as_of_date")
    as_of = _parse_date(as_of_raw, "as_of_date") if as_of_raw is not None else None

    base = {
        "capability": "qa.portrait_consent_gate",
        "portrait_id": pid,
        "intended_use": use,
        "digital_human_generation": "not_offered_by_this_gate",
        "supplier": None,
        "style_catalog": [dict(s) for s in _STYLES],
    }
    record = portraits.get(pid)
    if record is None:
        return {**base, "allowed": False, "verdict": "refused_unknown_portrait",
                "reason": "No portrait record exists for this id; unknown portraits are never authorised.",
                "styles_available": []}
    if record["consent"] == "denied":
        return {**base, "allowed": False, "verdict": "refused_consent_denied",
                "reason": "Consent status is denied.", "styles_available": []}
    if record["consent"] in ("pending", "unknown"):
        return {**base, "allowed": False, "verdict": "pending_no_authorisation",
                "reason": f"Consent status is {record['consent']}; no authorisation is on file.",
                "styles_available": []}
    if use not in record["scope"]:
        return {**base, "allowed": False, "verdict": "pending_scope_not_granted",
                "reason": "Authorised scope does not include the intended use.",
                "styles_available": []}
    if record["expires_parsed"] is not None:
        if as_of is None:
            return {**base, "allowed": False, "verdict": "pending_expiry_not_checked",
                    "reason": "Record has an expiry date but no as_of_date was supplied, so currency cannot be proven.",
                    "styles_available": []}
        if record["expires_parsed"] < as_of:
            return {**base, "allowed": False, "verdict": "refused_expired",
                    "reason": "Authorisation expired before as_of_date.",
                    "styles_available": []}
    styles = [dict(s) for s in _STYLES if style is None or s["id"] == style]
    return {**base, "allowed": True, "verdict": "allowed",
            "reason": "Authorisation is explicit, in scope, and current for the supplied date.",
            "styles_available": styles}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = gate_portrait(params.get("request"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "portrait_consent_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "allowed": result["allowed"], "verdict": result["verdict"]},
    )


def register_portrait_consent_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.portrait_consent_gate",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"request": {"type": "object"}},
            "required": ["request"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Authorised-portrait gate (clean-room): fail-closed consent, scope "
            "and expiry checks; styles only for authorised portraits, no "
            "digital-human generation, no supplier, no keys accepted."
        ),
        line="qa",
    ))
    return ["qa.portrait_consent_gate"]


register_portrait_consent_capabilities_once()
