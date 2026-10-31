"""Deterministic render gate (``qa.deterministic_render_gate``).

Clean-room rewrite of the determinism discipline behind HeyGen's
HyperFrames engine (Apache-2.0; see HYPERFRAMES_ATTRIBUTION.md).
No code, text or configuration from that repository is copied here.
This module judges render plans and recorded runs; it performs no
browser capture and no real encoding. The streaming-encoder
discipline is enforced at the contract layer only: chunk order
and per-chunk hash verification are plan fields, not an encoder
implementation.

Determinism rules enforced:

* Frame time is integer math: ``t = floor(frame) / fps``. The
  frame time is computed from the frame index alone, never from a
  wall clock.
* fps, width, height and every render variable are locked before
  frame 0. Any change after frame 0 fails.
* No wall-clock reads during render (``Date.now`` /
  ``performance.now`` / system timers), no unseeded randomness,
  no fetch during render.
* Capture must be atomic (BeginFrame-style): a frame is captured
  only as a whole, never mid-paint.
* The same input rendered twice must produce identical per-frame
  hashes, in order.

Failure contract: a malformed plan or run record (not a JSON
object, missing required fields) raises :class:`CapabilityError`.
A well-formed plan that violates a rule returns
``verdict: "fail"`` with named issues.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    register,
)

_Registered = False


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def frame_time(frame: int, fps: int) -> Fraction:
    """Frame time as exact integer math: floor(frame) / fps."""
    if not isinstance(frame, int) or isinstance(frame, bool):
        raise CapabilityError("frame must be an integer")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise CapabilityError("fps must be a positive integer")
    if frame < 0:
        raise CapabilityError("frame must be >= 0")
    return Fraction(frame, fps)


def check_render_plan(plan: Any) -> dict[str, Any]:
    """Judge a render plan against the determinism rules."""
    if not isinstance(plan, dict):
        raise CapabilityError("render plan must be a JSON object")
    issues: list[dict[str, Any]] = []
    fps = plan.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        issues.append(_issue("fps_invalid", "fps must be a positive integer", fps=fps))
    for field in ("width", "height"):
        value = plan.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            issues.append(
                _issue(f"{field}_invalid", f"{field} must be a positive integer", value=value)
            )
    locked = plan.get("locked_before_frame_0")
    if locked is not True:
        issues.append(
            _issue(
                "not_locked_before_frame_0",
                "fps, dimensions and render variables must be locked "
                "before frame 0",
                locked_before_frame_0=locked,
            )
        )
    for source in plan.get("wall_clock_sources") or []:
        issues.append(
            _issue(
                "wall_clock_source",
                f"wall-clock source {source!r} is forbidden during render",
                source=source,
            )
        )
    randomness = plan.get("randomness") or {}
    if not isinstance(randomness, dict):
        issues.append(_issue("randomness_malformed", "'randomness' must be an object"))
    elif randomness.get("seeded") is not True:
        issues.append(
            _issue(
                "unseeded_random",
                "randomness must be seeded (seeded=true with a seed); "
                "unseeded randomness is forbidden",
                randomness=randomness,
            )
        )
    if plan.get("fetch_during_render") is True:
        issues.append(
            _issue(
                "fetch_during_render",
                "fetch during render is forbidden; fetch only during setup",
            )
        )
    if plan.get("atomic_capture") is not True:
        issues.append(
            _issue(
                "capture_not_atomic",
                "capture must be atomic (BeginFrame-style whole-frame "
                "capture); screenshot-plus-wait is not atomic",
                atomic_capture=plan.get("atomic_capture"),
            )
        )
    encoder = plan.get("encoder") or {}
    if not isinstance(encoder, dict):
        issues.append(_issue("encoder_malformed", "'encoder' must be an object"))
    else:
        if encoder.get("chunk_order") not in ("sequential", "sharded_concat"):
            issues.append(
                _issue(
                    "encoder_chunk_order",
                    "encoder chunk order must be 'sequential' or "
                    "'sharded_concat'",
                    chunk_order=encoder.get("chunk_order"),
                )
            )
        if encoder.get("hash_check") is not True:
            issues.append(
                _issue(
                    "encoder_hash_check_missing",
                    "encoder must verify per-chunk hashes (hash_check=true)",
                )
            )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "issues": issues}


def check_lock_change(plan: Any, frame_index: int) -> dict[str, Any]:
    """A lock change after frame 0 fails; at frame 0 it is the lock itself."""
    if not isinstance(plan, dict):
        raise CapabilityError("render plan must be a JSON object")
    if frame_index > 0 and plan.get("lock_changed") is True:
        return {
            "verdict": "fail",
            "issues": [
                _issue(
                    "lock_changed_after_frame_0",
                    "fps, dimensions or variables changed after frame 0",
                    frame_index=frame_index,
                )
            ],
        }
    return {"verdict": "pass", "issues": []}


def check_render_reproducibility(run_a: Any, run_b: Any) -> dict[str, Any]:
    """Two runs of the same input must produce identical frame hashes."""
    if not isinstance(run_a, list) or not isinstance(run_b, list):
        raise CapabilityError("both runs must be lists of frame hashes")
    issues: list[dict[str, Any]] = []
    if len(run_a) != len(run_b):
        issues.append(
            _issue(
                "frame_count_mismatch",
                f"runs have different frame counts: {len(run_a)} vs {len(run_b)}",
                counts=[len(run_a), len(run_b)],
            )
        )
    for idx, (a, b) in enumerate(zip(run_a, run_b)):
        if a != b:
            issues.append(
                _issue(
                    "frame_hash_mismatch",
                    f"frame {idx} differs between runs",
                    frame=idx,
                )
            )
            break
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "frames_checked": min(len(run_a), len(run_b)),
        "issues": issues,
    }


def _render(params: dict[str, Any]) -> CapabilityResult:
    mode = params.get("mode", "plan")
    if mode == "reproducibility":
        result = check_render_reproducibility(
            params.get("run_a"), params.get("run_b")
        )
    elif mode == "lock":
        result = check_lock_change(params.get("plan"), int(params.get("frame_index", 0)))
    else:
        result = check_render_plan(params.get("plan"))
    return CapabilityResult(ok=result["verdict"] == "pass", output=result, files=[])


def register_deterministic_render_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.deterministic_render_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {},
                    "mode": {"type": "string"},
                    "run_a": {},
                    "run_b": {},
                    "frame_index": {"type": "integer"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Deterministic render gate (HyperFrames discipline, "
                "clean-room): frame time is integer math "
                "t=floor(frame)/fps, fps/dimensions/variables lock "
                "before frame 0, no wall clock, no unseeded randomness, "
                "no fetch during render, atomic capture, and two runs "
                "of the same input must hash identically. Contract "
                "layer only: no browser capture, no real encoder."
            ),
            line="qa",
        )
    )
    return ["qa.deterministic_render_gate"]
