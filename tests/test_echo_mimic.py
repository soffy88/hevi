"""EchoMimicV2 ComfyUI 工作流填参 + talking_face 引擎路由(无 GPU)。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.digital_human.talking_face import TalkingFaceUnavailable, generate_talking_face
from hevi.providers.echo_mimic.provider import echo_mimic_generate
from hevi.providers.h3_local.comfy_client import ComfyClient, H3ComfyError

_WF = (
    Path(__file__).resolve().parents[1]
    / "hevi/providers/echo_mimic/workflows/echomimic_v2_10g.json"
)


def test_workflow_template_is_api_format_10g() -> None:
    data = json.loads(_WF.read_text())
    assert data["sampler"]["class_type"] == "EchoMimicV2Node"
    assert data["sampler"]["inputs"]["if_low_varm"] is True
    assert data["sampler"]["inputs"]["store_in_varm"] is False
    assert data["sampler"]["inputs"]["width"] == "__WIDTH__"
    assert data["sampler"]["inputs"]["duration"] == "__DURATION__"


def test_build_workflow_fills_10g_envelope() -> None:
    client = ComfyClient(
        base_url="http://127.0.0.1:1",
        serial=False,
        workflows_dir=_WF.parent,
    )
    wf = client.build_workflow(
        "echomimic_v2_10g.json",
        prompt="",
        width=512,
        height=512,
        seed=7,
        ref_images=["ref.png"],
        extra_fills={"__AUDIO__": "drive.wav", "__DURATION__": 120, "__STEPS__": 20},
    )
    sampler = wf["sampler"]["inputs"]
    assert sampler["width"] == 512
    assert sampler["height"] == 512
    assert sampler["duration"] == 120
    assert sampler["steps"] == 20
    assert sampler["seed"] == 7
    assert wf["load_audio"]["inputs"]["audio"] == "drive.wav"
    assert wf["load_image"]["inputs"]["image"] == "ref.png"


def test_find_video_output_accepts_path_string() -> None:
    entry = {"outputs": {"sampler": {"video": "/home/soffy/ComfyUI/output/face.mp4"}}}
    item = ComfyClient.find_video_output(entry)
    assert item is not None
    assert item["filename"] == "face.mp4"
    assert item["type"] == "output"


@pytest.mark.asyncio
async def test_echo_mimic_rejects_1024() -> None:
    with pytest.raises(H3ComfyError, match="10G"):
        await echo_mimic_generate(
            image_path=__file__,
            audio_path=__file__,
            output_path="/tmp/out.mp4",
            width=1024,
            height=1024,
        )


@pytest.mark.asyncio
async def test_talking_face_echomimic_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALKING_FACE_ENGINE", "echomimic")
    image = tmp_path / "face.jpg"
    audio = tmp_path / "line.wav"
    image.write_bytes(b"\xff\xd8\xff")
    audio.write_bytes(b"RIFF....")
    out = tmp_path / "talk.mp4"

    async def _fake(**_kw: object) -> Path:
        out.write_bytes(b"fake-echo-mp4")
        return out

    with (
        patch(
            "hevi.digital_human.talking_face._engine_capabilities",
            AsyncMock(return_value={"longcat": False}),
        ),
        patch("hevi.digital_human.talking_face._run_echo_mimic", _fake),
    ):
        result = await generate_talking_face(
            image_path=image, audio_path=audio, output_path=out
        )
    assert result == out
    assert out.read_bytes() == b"fake-echo-mp4"


@pytest.mark.asyncio
async def test_talking_face_echomimic_does_not_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TALKING_FACE_ENGINE", "echomimic")
    image = tmp_path / "face.jpg"
    audio = tmp_path / "line.wav"
    image.write_bytes(b"\xff\xd8\xff")
    audio.write_bytes(b"RIFF....")
    out = tmp_path / "talk.mp4"
    with (
        patch(
            "hevi.digital_human.talking_face._engine_capabilities",
            AsyncMock(return_value={"longcat": False}),
        ),
        patch(
            "hevi.digital_human.talking_face._run_echo_mimic",
            AsyncMock(side_effect=TalkingFaceUnavailable("comfy down")),
        ),
        patch(
            "hevi.digital_human.talking_face._generate_placeholder_avoiding_null",
            AsyncMock(side_effect=AssertionError("must not placeholder")),
        ),
    ):
        with pytest.raises(TalkingFaceUnavailable, match="comfy down"):
            await generate_talking_face(
                image_path=image, audio_path=audio, output_path=out
            )
