"""Atomic frame capture via Chromium ``HeadlessExperimental.beginFrame``.

Clean-room implementation of the atomic-capture *idea* behind HeyGen's
HyperFrames engine (Apache-2.0; see
``hevi/capabilities/HYPERFRAMES_ATTRIBUTION.md``). No upstream code is
copied. This module speaks Chromium's own CDP domain directly through a
Playwright CDP session; it is not upstream HyperFrames code.

What was verified on ubuntu26 (2026-10-31, Playwright 1.62.0, Chromium
headless-shell 1248): with the launch flags in
:const:`BEGINFRAME_CHROMIUM_ARGS`, a CDP ``beginFrame`` call returns
``screenshotData``; four captures at the same seek hash identically and a
different seek hashes differently (see the B4 verification matrix,
``docs/csk_style_verification_matrix.md``). Two probe pitfalls are
recorded here so they are not rediscovered:

* ``interval`` is in **milliseconds** (protocol: "about 16.666" for
  60 fps). Passing ``0.016`` (seconds) makes ``beginFrame`` return only
  ``hasDamage`` and no screenshot data, silently.
* ``frameTimeTicks`` must be omitted (current time is used) or be a
  fresh uptime value; a stale value can hang the call. This module
  always omits it.
* ``Page.captureScreenshot`` after ``beginFrame`` deadlocks in this
  stack (the compositor is under manual BeginFrame control): in
  beginFrame mode this module never calls it.

Capture contract: after the caller seeks the page, :func:`capture_frame`
sends one ``beginFrame`` and returns the screenshot bytes. A response
without ``screenshotData`` raises :class:`BeginFrameCaptureError`
instead of returning a blank frame. Callers that need the atomicity
self-check use :func:`capture_frame_settled`, which captures twice and
requires identical hashes — a frame whose pixels are still moving
(blur-in transition not landed) is refused, not delivered.

streamingEncoder: CONTRACT ONLY. :func:`streaming_encoder_contract`
describes chunked pipe encoding (frames piped to ffmpeg stdin in order,
segments concatenated) without implementing it; hevi still encodes
from a PNG sequence (``csk_styled_render._encode_mp4``). Nothing in
this module claims a streaming encoder exists.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BEGINFRAME_CHROMIUM_ARGS",
    "BeginFrameCaptureError",
    "BeginFrameUnavailable",
    "BeginFrameResult",
    "capture_frame",
    "capture_frame_settled",
    "probe_beginframe",
    "streaming_encoder_contract",
]

# Both flags are required together (verified by probe): without the
# compositor flag Chromium answers "Command is only supported with
# --run-all-compositor-stages-before-draw"; without the control flag it
# answers "Command is only supported if BeginFrameControl is enabled".
BEGINFRAME_CHROMIUM_ARGS: tuple[str, ...] = (
    "--enable-begin-frame-control",
    "--run-all-compositor-stages-before-draw",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--disable-checker-imaging",
)


class BeginFrameUnavailable(RuntimeError):
    """beginFrame cannot be used in this browser/session (layer recorded)."""

    def __init__(self, message: str, *, layer: str) -> None:
        super().__init__(message)
        self.layer = layer


class BeginFrameCaptureError(RuntimeError):
    """beginFrame answered but produced no usable screenshot."""


@dataclass
class BeginFrameResult:
    """One atomically captured frame."""

    png_or_jpeg: bytes
    sha256: str
    has_damage: bool


def _beginframe_params(fps: int, image_format: str) -> dict[str, Any]:
    if fps <= 0:
        raise ValueError("fps must be positive")
    if image_format not in ("png", "jpeg"):
        raise ValueError("image_format must be 'png' or 'jpeg'")
    params: dict[str, Any] = {
        "interval": 1000.0 / fps,
        "screenshot": {"format": image_format},
    }
    if image_format == "jpeg":
        params["screenshot"]["quality"] = 90
    return params


async def capture_frame(
    cdp_session: Any,
    *,
    fps: int,
    image_format: str = "png",
) -> BeginFrameResult:
    """Capture one frame atomically via CDP ``beginFrame``.

    ``cdp_session`` is a Playwright CDP session (``page.context
    .new_cdp_session(page)``). The caller must have seeked the page
    first; this function only drives the compositor and captures.
    """
    params = _beginframe_params(fps, image_format)
    try:
        response = await cdp_session.send("HeadlessExperimental.beginFrame", params)
    except Exception as exc:  # noqa: BLE001 - map to the layer taxonomy
        text = str(exc)
        if "BeginFrameControl" in text:
            raise BeginFrameUnavailable(
                "beginFrame rejected: BeginFrameControl is not enabled; "
                "launch Chromium with BEGINFRAME_CHROMIUM_ARGS",
                layer="launch_flags",
            ) from exc
        if "run-all-compositor-stages-before-draw" in text:
            raise BeginFrameUnavailable(
                "beginFrame rejected: --run-all-compositor-stages-before-draw "
                "is missing from the Chromium launch args",
                layer="launch_flags",
            ) from exc
        raise BeginFrameUnavailable(
            f"beginFrame CDP call failed: {exc}", layer="cdp_session"
        ) from exc
    data = response.get("screenshotData") if isinstance(response, dict) else None
    if not data:
        raise BeginFrameCaptureError(
            "beginFrame returned no screenshotData (hasDamage="
            f"{response.get('hasDamage') if isinstance(response, dict) else '?'}); "
            "the screenshot capture failed inside Chromium -- refusing "
            "to treat an empty frame as a capture"
        )
    raw = base64.b64decode(data)
    return BeginFrameResult(
        png_or_jpeg=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        has_damage=bool(response.get("hasDamage")),
    )


async def capture_frame_settled(
    cdp_session: Any,
    *,
    fps: int,
    image_format: str = "png",
) -> BeginFrameResult:
    """Capture twice; require identical hashes (atomicity self-check).

    Two consecutive beginFrame captures of a settled seek must agree
    byte-for-byte. Disagreement means pixels were still moving (an
    animation/blur transition had not landed) and the frame is refused
    with :class:`BeginFrameCaptureError` instead of being delivered as
    a half-drawn frame.
    """
    first = await capture_frame(cdp_session, fps=fps, image_format=image_format)
    second = await capture_frame(cdp_session, fps=fps, image_format=image_format)
    if first.sha256 != second.sha256:
        raise BeginFrameCaptureError(
            "beginFrame captures at the same seek disagree "
            f"({first.sha256[:12]} vs {second.sha256[:12]}); frame not "
            "settled -- refusing to deliver a half-drawn frame"
        )
    return first


async def probe_beginframe(
    cdp_session: Any,
    *,
    fps: int = 24,
) -> dict[str, Any]:
    """Probe whether beginFrame capture works on this session.

    Captures the current seek twice and reports repeat-identical state.
    Never raises for a failed capture: the failure (with its layer) is
    returned in the report so callers can record the residual honestly.
    """
    try:
        first = await capture_frame(cdp_session, fps=fps)
        second = await capture_frame(cdp_session, fps=fps)
    except (BeginFrameUnavailable, BeginFrameCaptureError) as exc:
        return {
            "available": False,
            "layer": getattr(exc, "layer", "capture"),
            "error": str(exc),
        }
    return {
        "available": True,
        "repeat_identical": first.sha256 == second.sha256,
        "sha256": first.sha256,
        "screenshot_bytes": len(first.png_or_jpeg),
    }


def streaming_encoder_contract() -> dict[str, Any]:
    """Contract for a streaming encoder. CONTRACT ONLY -- not implemented.

    A streaming encoder would pipe frames to ffmpeg stdin in order as
    they are captured (chunked, segment-concatenated), instead of
    writing a PNG sequence to disk and encoding afterwards. hevi has
    no such encoder: ``csk_styled_render`` still encodes from PNG
    files. This dict exists so the gap is named and checkable, not
    silently implied by the beginFrame work.
    """
    return {
        "name": "streamingEncoder",
        "status": "contract_only",
        "implemented": False,
        "contract": {
            "input": "frames in capture order, piped to ffmpeg stdin",
            "output": "one MP4, segments concatenated in order",
            "requirement": "no full PNG sequence on disk; backpressure from the encoder",
        },
        "current_implementation": (
            "PNG sequence on disk + ffmpeg image2pipe "
            "(hevi/video/csk_styled_render.py::_encode_mp4)"
        ),
    }
