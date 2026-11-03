"""Unified ``window.__hf`` frame adapter (converged seek protocol).

Clean-room implementation of the FrameAdapter *concept* behind
HeyGen's HyperFrames engine (Apache-2.0; see
``hevi/capabilities/HYPERFRAMES_ATTRIBUTION.md``). No upstream
code is copied. This module is the single seek protocol all
hevi code-animation renderers converge on:

* ``window.__hf`` on the page, with ``getDurationFrames`` /
  ``seekFrame`` / ``destroy`` semantics (here as the Python-side
  :class:`FrameAdapter` driving a seek callable).
* Any frame may be requested in any order and must be
  reproducible: frame time is ``floor(frame) / fps`` integer
  math, never a wall clock.
* After a seek, capture waits for *settle confirmation*:
  successive captures must agree before the frame is accepted.
  A fixed wait is not a confirmation.

Legacy protocols are deprecated shims only:

* ``window.__timelines`` (``csk_styled_render.py`` shim) --
  deprecated, kept for compatibility.
* ``window.HF`` (``hyperframes_seek.py``) -- deprecated alias;
  ``HF`` now forwards to the ``__hf`` adapter concept and new
  code must use ``__hf``.
* Per-frame fresh browsers (``hyperframes_service.py``) --
  deprecated; reuse one browser session.

Naming correction: CSK styles are creator-style-kit style
templates rendered by hevi's own renderers, not the HeyGen
HyperFrames engine. This adapter implements hevi's converged
protocol; it is not upstream HyperFrames code.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable, Sequence

__all__ = [
    "PROTOCOL",
    "DEPRECATED_PROTOCOLS",
    "FrameAdapter",
    "frame_time_seconds",
    "settle_capture",
]

PROTOCOL = "__hf"
DEPRECATED_PROTOCOLS = ("__timelines", "HF", "fresh_browser_per_frame")


def frame_time_seconds(frame: int, fps: int) -> float:
    """Frame time: floor(frame) / fps, integer math, never a wall clock."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    if frame < 0:
        raise ValueError("frame must be >= 0")
    return math.floor(frame) / fps


@dataclass
class FrameAdapter:
    """Drive a seek callable under the converged ``__hf`` protocol.

    ``seek`` moves the page to frame ``n`` (0-based) and returns
    nothing; ``capture`` returns the current frame's bytes.
    ``settle_capture`` polls ``capture`` until two consecutive
    captures hash identically (settled) or ``max_attempts`` is
    exhausted, in which case it raises :class:`RuntimeError`
    instead of returning an unsettled frame.
    """

    total_frames: int
    fps: int
    seek: Callable[[int], None]
    capture: Callable[[], bytes]
    max_attempts: int = 50

    def get_duration_frames(self) -> int:
        return self.total_frames

    def seek_frame(self, frame: int) -> bytes:
        if not 0 <= frame < self.total_frames:
            raise ValueError(f"frame {frame} out of range [0, {self.total_frames})")
        self.seek(frame)
        return settle_capture(self.capture, max_attempts=self.max_attempts)

    def destroy(self) -> None:
        """Release adapter resources. No-op for the base adapter."""


def settle_capture(
    capture: Callable[[], bytes],
    *,
    max_attempts: int = 50,
) -> bytes:
    """Poll captures until two consecutive captures agree."""
    if max_attempts < 2:
        raise ValueError("max_attempts must be >= 2")
    previous: bytes | None = None
    previous_hash: str | None = None
    for _ in range(max_attempts):
        current = capture()
        digest = hashlib.sha256(current).hexdigest()
        if previous is not None and digest == previous_hash:
            return current
        previous, previous_hash = current, digest
    raise RuntimeError(
        f"frame did not settle after {max_attempts} captures; "
        "refusing to return an unsettled frame"
    )


def sequence_digests(frames: Sequence[bytes]) -> list[str]:
    """Per-frame sha256 digests, for reproducibility checks."""
    return [hashlib.sha256(frame).hexdigest() for frame in frames]
