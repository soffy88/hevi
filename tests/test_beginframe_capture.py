"""Tests for beginFrame atomic capture (contract + fake-CDP unit tests).

Real-browser verification (repeat-identical hashes, seek-differs, blur
judgement) is recorded in docs/csk_style_verification_matrix.md from the
B4 driver run; these tests cover the error taxonomy and the
streaming-encoder contract without a browser.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from hevi.video.beginframe_capture import (
    BEGINFRAME_CHROMIUM_ARGS,
    BeginFrameCaptureError,
    BeginFrameUnavailable,
    capture_frame,
    capture_frame_settled,
    probe_beginframe,
    streaming_encoder_contract,
)

PNG_1X1 = base64.b64encode(b"\x89PNG-fake-frame-bytes").decode("ascii")


class FakeSession:
    """CDP session stub: returns queued responses or raises queued errors."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def send(self, method, params=None):
        self.calls.append((method, params))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _frame_response(payload: bytes = b"\x89PNG-fake-frame-bytes"):
    return {"hasDamage": True, "screenshotData": base64.b64encode(payload).decode("ascii")}


def test_launch_args_enable_beginframe_control() -> None:
    assert "--enable-begin-frame-control" in BEGINFRAME_CHROMIUM_ARGS
    assert "--run-all-compositor-stages-before-draw" in BEGINFRAME_CHROMIUM_ARGS


@pytest.mark.asyncio
async def test_capture_frame_returns_bytes_and_hash() -> None:
    session = FakeSession([_frame_response()])
    result = await capture_frame(session, fps=4)
    assert result.png_or_jpeg == b"\x89PNG-fake-frame-bytes"
    assert result.sha256 == hashlib.sha256(b"\x89PNG-fake-frame-bytes").hexdigest()
    assert result.has_damage is True
    method, params = session.calls[0]
    assert method == "HeadlessExperimental.beginFrame"
    # interval is milliseconds per the CDP protocol (16.666 at 60fps),
    # frameTimeTicks is omitted (current time is used).
    assert params["interval"] == pytest.approx(250.0)
    assert "frameTimeTicks" not in params
    assert params["screenshot"]["format"] == "png"


@pytest.mark.asyncio
async def test_capture_frame_without_screenshot_data_raises() -> None:
    session = FakeSession([{"hasDamage": True}])
    with pytest.raises(BeginFrameCaptureError, match="no screenshotData"):
        await capture_frame(session, fps=4)


@pytest.mark.asyncio
async def test_capture_frame_maps_beginframe_control_error_to_layer() -> None:
    session = FakeSession([
        RuntimeError("Protocol error (HeadlessExperimental.beginFrame): "
                     "Command is only supported if BeginFrameControl is enabled."),
    ])
    with pytest.raises(BeginFrameUnavailable) as excinfo:
        await capture_frame(session, fps=4)
    assert excinfo.value.layer == "launch_flags"


@pytest.mark.asyncio
async def test_capture_frame_maps_compositor_flag_error_to_layer() -> None:
    session = FakeSession([
        RuntimeError("Command is only supported with "
                     "--run-all-compositor-stages-before-draw"),
    ])
    with pytest.raises(BeginFrameUnavailable) as excinfo:
        await capture_frame(session, fps=4)
    assert excinfo.value.layer == "launch_flags"


@pytest.mark.asyncio
async def test_capture_frame_settled_accepts_identical_captures() -> None:
    session = FakeSession([_frame_response(), _frame_response()])
    result = await capture_frame_settled(session, fps=4)
    assert result.sha256 == hashlib.sha256(b"\x89PNG-fake-frame-bytes").hexdigest()
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_capture_frame_settled_refuses_moving_frame() -> None:
    session = FakeSession([_frame_response(b"frame-a"), _frame_response(b"frame-b")])
    with pytest.raises(BeginFrameCaptureError, match="not settled"):
        await capture_frame_settled(session, fps=4)


@pytest.mark.asyncio
async def test_probe_reports_unavailable_without_raising() -> None:
    session = FakeSession([{"hasDamage": False}])
    report = await probe_beginframe(session, fps=4)
    assert report["available"] is False
    assert report["layer"] == "capture"


@pytest.mark.asyncio
async def test_probe_reports_available_and_repeat_identical() -> None:
    session = FakeSession([_frame_response(), _frame_response()])
    report = await probe_beginframe(session, fps=4)
    assert report["available"] is True
    assert report["repeat_identical"] is True


def test_streaming_encoder_is_contract_only() -> None:
    contract = streaming_encoder_contract()
    assert contract["implemented"] is False
    assert contract["status"] == "contract_only"
    assert "PNG sequence" in contract["current_implementation"]
