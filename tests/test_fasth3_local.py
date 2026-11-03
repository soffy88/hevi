"""Tests for video.fasth3_local.

Unit tests are fully mocked (no ComfyUI, no GPU, no ffmpeg run): they pin
the locked official values, the 5-15 s refusal, and the verbatim-error
policy.  The real-clip test is gated on HEVI_FASTH3_REAL_TEST=1 and
only runs on ubuntu26, where ComfyUI serves localhost:8188; it renders
one real 5 s clip from the in-hand reference still and probes it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import hevi.capabilities.fasth3_local as fl
from hevi.capabilities import get as cap_get
from hevi.capabilities.errors import CapabilityError


def test_capability_registered() -> None:
    cap = cap_get("video.fasth3_local")
    assert cap.name == "video.fasth3_local"
    assert cap.aspects == ["16:9"]


def test_workflow_locks_official_values() -> None:
    wf = fl.build_workflow("ref.jpg", "<Picture 1> test", 192, 777, "p")
    assert wf["9"]["inputs"]["steps"] == 8
    assert wf["9"]["inputs"]["cfg"] == 1.0
    assert wf["9"]["inputs"]["sampler_name"] == "euler"
    assert wf["9"]["inputs"]["scheduler"] == "simple"
    assert wf["7"]["inputs"]["shift_video"] == 12.0
    assert wf["7"]["inputs"]["shift_audio"] == 3.0
    assert wf["2"]["inputs"]["unet_name"].endswith("_int8_convrot.safetensors")
    assert wf["3"]["inputs"]["clip_name"].endswith("_int8_convrot.safetensors")
    assert wf["4"]["inputs"]["vae_name"].endswith("_int8_convrot.safetensors")
    assert wf["5"]["inputs"]["vae_name"].endswith("_fp32.safetensors")
    assert wf["6"]["inputs"]["width"] == 1024
    assert wf["6"]["inputs"]["height"] == 576
    assert wf["6"]["inputs"]["length"] == 192
    # Working ref shape (flat ref_image_1 is the known failure mode).
    assert wf["6"]["inputs"]["ref_images"] == {"ref_image_1": ["1", 0]}
    assert "ref_image_1" not in wf["6"]["inputs"]


@pytest.mark.parametrize("bad", [4.9, 0.0, 15.1, 30.0])
def test_duration_outside_trained_interval_refused(
        tmp_path: Path, bad: float, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = tmp_path / "r.jpg"
    ref.write_bytes(b"JPEG")
    monkeypatch.setattr(fl, "_check_gpu", lambda: 8000)
    with pytest.raises(CapabilityError, match="outside trained interval"):
        fl.render({"reference_image": str(ref), "prompt": "<Picture 1> x"},
                  tmp_path / "out", duration=bad, aspect="16:9")


def test_comfy_execution_error_surfaces_verbatim(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = tmp_path / "r.jpg"
    ref.write_bytes(b"JPEG")
    monkeypatch.setattr(fl, "_check_gpu", lambda: 8000)
    monkeypatch.setattr(fl, "_upload_image", lambda b, p: "r.jpg")
    monkeypatch.setattr(fl, "_http_json",
                        lambda b, p, payload=None: {"prompt_id": "pid1"})

    def _bad_poll(base_url, prompt_id, timeout_s, poll_interval_s=10.0):
        raise CapabilityError(
            "video.fasth3_local: ComfyUI execution error (raw history): "
            '{"status": {"status_str": "error"}, "node_id": "6", '
            '"exception_message": "MiniMaxH3ReferenceToVideo.execute() got '
            'an unexpected keyword argument \'ref_image_1\'"}')

    monkeypatch.setattr(fl, "_poll_history", _bad_poll)
    with pytest.raises(CapabilityError) as excinfo:
        fl.render({"reference_image": str(ref), "prompt": "<Picture 1> x"},
                  tmp_path / "out", duration=5.0, aspect="16:9")
    assert "unexpected keyword argument 'ref_image_1'" in str(excinfo.value)


def test_render_happy_path_mocked(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = tmp_path / "r.jpg"
    ref.write_bytes(b"JPEG")
    mp4 = tmp_path / "real.mp4"
    mp4.write_bytes(b"MP4")
    monkeypatch.setattr(fl, "_check_gpu", lambda: 9000)
    monkeypatch.setattr(fl, "_upload_image", lambda b, p: "r.jpg")
    monkeypatch.setattr(fl, "_http_json",
                        lambda b, p, payload=None: {"prompt_id": "pid9"})
    monkeypatch.setattr(
        fl, "_poll_history",
        lambda b, pid, t, poll_interval_s=10.0: (
            {"13": {"images": [{"filename": "p_00001_.mp4",
                                "subfolder": "", "type": "output"}]}},
            12.5, 9854))
    monkeypatch.setattr(fl, "_download_output",
                        lambda b, o, dest: dest.write_bytes(b"MP4") or dest)
    monkeypatch.setattr(fl, "_probe_mp4",
                        lambda p: {"duration_s": 5.1667, "width": 1024,
                                    "height": 576, "video_codec": "h264",
                                    "audio_codec": "aac"})
    result = fl.render({"reference_image": str(ref), "prompt": "<Picture 1> x"},
                       tmp_path / "out", duration=5.0, aspect="16:9")
    assert result.mp4.endswith("fasth3_local.mp4")
    assert result.duration_s == pytest.approx(5.1667)
    assert result.qa["frames"] == 124
    assert result.qa["peak_vram_mib"] == 9854
    assert (tmp_path / "out" / "fasth3_meta.json").exists()


@pytest.mark.skipif(os.environ.get("HEVI_FASTH3_REAL_TEST") != "1",
                    reason="real ComfyUI clip only on ubuntu26 with opt-in")
def test_real_5s_clip(tmp_path: Path) -> None:
    ref = Path("/data/soffy/fasth3-comfy/ComfyUI/input/ref_school.jpg")
    assert ref.exists(), "reference still missing on this host"
    result = fl.render(
        {"reference_image": str(ref),
         "prompt": "<Picture 1> In a Ming dynasty private school classroom "
                   "in warm candlelight, the 12-year-old boy in the blue "
                   "headband stands up from his desk and speaks to his "
                   "teacher while his classmates laugh around him. The "
                   "camera holds steady. Natural motion, synchronized "
                   "classroom ambience and voices. All dialogue in "
                   "Mandarin Chinese."},
        tmp_path / "real", duration=5.0, aspect="16:9")
    assert Path(result.mp4).exists()
    assert result.duration_s == pytest.approx(5.1667, abs=0.6)
    assert result.qa["probe"]["width"] == 1024
    assert result.qa["probe"]["height"] == 576
    assert result.qa["probe"]["audio_codec"] is not None
