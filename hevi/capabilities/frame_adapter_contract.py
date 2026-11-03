"""Frame-adapter contract (``qa.frame_adapter_contract``).

Clean-room rewrite of the *discipline* behind HeyGen's HyperFrames
FrameAdapter concept (Apache-2.0; see HYPERFRAMES_ATTRIBUTION.md).
No code, text or configuration from that repository is copied here.
This module judges plans and renderer declarations; it performs no
browser capture itself.

The contract, in one paragraph: every code-animation renderer in
hevi speaks one seek protocol, ``window.__hf``. An adapter exposes
``getDurationFrames`` / ``seekFrame`` / ``destroy``; any frame may
be requested in any order and must be reproducible; after a seek
the adapter must *confirm* the frame has settled before capture --
a fixed wait is not a confirmation. The three legacy protocols
found in hevi (``window.__timelines`` in ``csk_styled_render.py``,
``window.HF`` in ``hyperframes_seek.py``, per-frame fresh browsers
in ``hyperframes_service.py``) are deprecated shims: they keep
working only when a caller explicitly opts into a legacy shim, and
every such use is reported as a deprecation, never silently
accepted as the converged protocol.

Naming correction (report ``hevi-vs-hyperframes-deepdive.md`` §1):
the CSK 18 styles are creator-style-kit style templates rendered
by hevi's own renderers. They are NOT the HeyGen HyperFrames
engine. Capability names such as ``video.hyperframes_styles``
are kept stable for call-chain compatibility; their descriptions
and the attribution file state the distinction plainly.

Failure contract: a malformed plan (not a JSON object, missing
``adapter``/``renderer`` sections where required) raises
:class:`CapabilityError`. A well-formed plan that violates the
contract returns ``verdict: "fail"`` with named issues; it never
raises.
"""

from __future__ import annotations

from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    register,
)

PROTOCOL = "__hf"
REQUIRED_METHODS = ("getDurationFrames", "seekFrame", "destroy")
LEGACY_PROTOCOLS = {
    "__timelines": "csk_styled_render shim (window.__timelines)",
    "HF": "hyperframes_seek window.HF protocol",
    "fresh_browser_per_frame": "hyperframes_service per-frame browser",
}

_Registered = False


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _is_obj(value: Any) -> bool:
    return isinstance(value, dict)


def check_adapter_plan(plan: Any, *, allow_legacy_shim: bool = False) -> dict[str, Any]:
    """Judge one adapter declaration against the ``__hf`` contract."""
    if not _is_obj(plan):
        raise CapabilityError("adapter plan must be a JSON object")
    adapter = plan.get("adapter")
    if not _is_obj(adapter):
        raise CapabilityError("adapter plan requires an 'adapter' object")
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    protocol = adapter.get("protocol")
    if protocol in LEGACY_PROTOCOLS:
        if allow_legacy_shim:
            warnings.append(
                _issue(
                    "legacy_protocol_deprecated",
                    f"legacy protocol {protocol!r} used via explicit shim "
                    f"({LEGACY_PROTOCOLS[protocol]}); migrate to {PROTOCOL!r}",
                    protocol=protocol,
                )
            )
        else:
            issues.append(
                _issue(
                    "legacy_protocol",
                    f"protocol {protocol!r} is a deprecated legacy protocol "
                    f"({LEGACY_PROTOCOLS[protocol]}); converged protocol "
                    f"is {PROTOCOL!r}",
                    protocol=protocol,
                )
            )
    elif protocol != PROTOCOL:
        issues.append(
            _issue(
                "protocol_mismatch",
                f"adapter protocol must be {PROTOCOL!r}, got {protocol!r}",
                protocol=protocol,
            )
        )
    methods = adapter.get("methods")
    if not isinstance(methods, list):
        issues.append(
            _issue("methods_missing", "adapter 'methods' must be a list", methods=methods)
        )
        methods = []
    for name in REQUIRED_METHODS:
        if name not in methods:
            issues.append(
                _issue(
                    "method_missing",
                    f"adapter must expose {name!r}",
                    method=name,
                )
            )
    settle = adapter.get("settle")
    if not _is_obj(settle):
        issues.append(
            _issue(
                "settle_missing",
                "adapter must declare a 'settle' confirmation block",
            )
        )
    else:
        mode = settle.get("mode")
        if mode != "confirmation":
            issues.append(
                _issue(
                    "settle_not_confirmed",
                    "settle mode must be 'confirmation' (settle confirmed "
                    "before capture); a fixed wait is not a confirmation",
                    mode=mode,
                )
            )
        max_wait = settle.get("max_wait_ms")
        if not isinstance(max_wait, (int, float)) or isinstance(max_wait, bool) or max_wait <= 0:
            issues.append(
                _issue(
                    "settle_max_wait_invalid",
                    "'settle.max_wait_ms' must be a positive number",
                    max_wait_ms=max_wait,
                )
            )
    if adapter.get("arbitrary_order") is not True:
        issues.append(
            _issue(
                "arbitrary_order_missing",
                "adapter must declare arbitrary_order=true: any frame "
                "may be requested in any order and must be reproducible",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "protocol": PROTOCOL,
        "declared_protocol": protocol,
        "issues": issues,
        "warnings": warnings,
    }


def check_renderer_protocols(renderers: Any) -> dict[str, Any]:
    """All renderers must declare the same converged protocol."""
    if not isinstance(renderers, list) or not renderers:
        raise CapabilityError("renderers must be a non-empty list")
    issues: list[dict[str, Any]] = []
    declared: list[dict[str, Any]] = []
    for entry in renderers:
        if not _is_obj(entry):
            raise CapabilityError("each renderer entry must be a JSON object")
        name = entry.get("name")
        protocol = entry.get("protocol")
        declared.append({"name": name, "protocol": protocol})
        if protocol != PROTOCOL:
            issues.append(
                _issue(
                    "renderer_protocol_divergence",
                    f"renderer {name!r} declares protocol {protocol!r}; "
                    f"converged protocol is {PROTOCOL!r}",
                    name=name,
                    protocol=protocol,
                )
            )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "protocol": PROTOCOL, "renderers": declared, "issues": issues}


def check_frame_sequence(frames: Any) -> dict[str, Any]:
    """Judge a captured frame sequence: settled captures, reproducible frames."""
    if not isinstance(frames, list):
        raise CapabilityError("frames must be a list")
    issues: list[dict[str, Any]] = []
    seen: dict[Any, Any] = {}
    for entry in frames:
        if not _is_obj(entry):
            raise CapabilityError("each frame entry must be a JSON object")
        frame_no = entry.get("frame")
        if entry.get("settled") is not True:
            issues.append(
                _issue(
                    "frame_not_settled",
                    f"frame {frame_no!r} was captured without settle confirmation",
                    frame=frame_no,
                )
            )
        digest = entry.get("sha256")
        if frame_no in seen and seen[frame_no] != digest:
            issues.append(
                _issue(
                    "frame_not_reproducible",
                    f"frame {frame_no!r} captured twice with different hashes",
                    frame=frame_no,
                )
            )
        seen[frame_no] = digest
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "frames_checked": len(frames), "issues": issues}


def _render(params: dict[str, Any]) -> CapabilityResult:
    plan = params.get("plan")
    mode = params.get("mode", "adapter")
    if mode == "renderers":
        result = check_renderer_protocols(plan)
    elif mode == "frames":
        result = check_frame_sequence(plan)
    else:
        result = check_adapter_plan(
            plan, allow_legacy_shim=bool(params.get("allow_legacy_shim", False))
        )
    return CapabilityResult(
        ok=result["verdict"] == "pass",
        output=result,
        files=[],
    )


def register_frame_adapter_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.frame_adapter_contract",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {},
                    "mode": {"type": "string"},
                    "allow_legacy_shim": {"type": "boolean"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Frame-adapter contract (HyperFrames discipline, clean-room): "
                "one converged seek protocol window.__hf with "
                "getDurationFrames/seekFrame/destroy, arbitrary-order "
                "reproducible frames, and settle confirmation before "
                "capture; legacy __timelines/HF/fresh-browser protocols "
                "are deprecated shims. CSK styles are style templates "
                "rendered by hevi's own renderers, not the HeyGen "
                "HyperFrames engine. Plan and gate only: no browser "
                "capture is performed here."
            ),
            line="qa",
        )
    )
    return ["qa.frame_adapter_contract"]
