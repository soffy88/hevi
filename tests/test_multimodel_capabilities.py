"""Contract tests for the multimodel capabilities (CAPABILITY_CONTRACT.md).

Offline: the Monid layer is monkeypatched, so no key and no network are needed.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.audio import monid_client


def test_multimodel_capabilities_registered_and_listable() -> None:
    names = caps.names()
    for expected in ("audio.forced_align", "image.gpt_generate", "image.gpt_edit"):
        assert expected in names
    listed = [c.name for c in caps.list(kind="audio")] + [
        c.name for c in caps.list(kind="shot")
    ]
    assert "audio.forced_align" in listed
    assert "image.gpt_generate" in listed
    assert "image.gpt_edit" in listed


def test_multimodel_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in ("audio.forced_align", "image.gpt_generate", "image.gpt_edit"):
        assert expected in by_name
        assert by_name[expected].get("description"), expected


def test_forced_align_rejects_invalid_params() -> None:
    cap = caps.get("audio.forced_align")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, Path("/tmp/mm-align"), duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"audio_path": "a.wav"},  # missing required text
            Path("/tmp/mm-align"),
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_gpt_edit_rejects_missing_prompt_and_extra_params() -> None:
    cap = caps.get("image.gpt_edit")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"image_paths": ["a.png"]},  # missing required prompt
            Path("/tmp/mm-edit"),
            duration=1.0,
            aspect="9:16",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"image_paths": ["a.png"], "prompt": "x", "bogus": 1},
            Path("/tmp/mm-edit"),
            duration=1.0,
            aspect="9:16",
            seed=1,
        )


def test_forced_align_render_writes_sidecar_and_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import forced_alignment
    from hevi.audio.tts_alignment import WordTiming

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFFfake")
    captured: dict[str, object] = {}

    async def fake_align(*, audio_path: Path, text: str, **kwargs):
        captured["audio_path"] = audio_path
        captured["text"] = text
        return (WordTiming("黑洞", 240, 610), WordTiming("形成", 660, 920)), 0.0012

    monkeypatch.setattr(forced_alignment, "forced_align_words", fake_align)

    cap = caps.get("audio.forced_align")
    out_dir = tmp_path / "out"
    result = cap.render_safe(
        {"audio_path": str(audio), "text": "黑洞 形成"},
        out_dir,
        duration=1.0,
        aspect="16:9",
        seed=7,
    )
    assert result.wav == str(audio)
    assert result.qa["is_estimated"] is False
    assert result.qa["word_count"] == 2
    assert result.qa["cost"] == 0.0012
    assert captured["text"] == "黑洞 形成"

    sidecar = Path(result.qa["alignment_json"])
    assert sidecar.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["alignment_source"] == "elevenlabs_forced_alignment"
    assert payload["is_estimated"] is False
    assert payload["words"][0]["start_ms"] == 240

    sidecar.unlink()
    assert not sidecar.exists(), "contract: deleting the artifact must break verification"


def test_gpt_generate_render_writes_png_with_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.image import gpt_image_service

    async def fake_generate(*, prompt, output_path, size="1024x1536", quality="medium", **_):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"pngbytes")
        return {"output_path": str(output_path), "cost": 0.0107}

    monkeypatch.setattr(gpt_image_service, "gpt_image_generate", fake_generate)

    cap = caps.get("image.gpt_generate")
    out_dir = tmp_path / "img"
    result = cap.render_safe(
        {"prompt": "a host in a studio"}, out_dir, duration=1.0, aspect="9:16", seed=3
    )
    assert result.png is not None
    png = Path(result.png)
    assert png.is_file() and png.read_bytes() == b"pngbytes"
    assert result.sha256
    assert result.qa["cost"] == 0.0107

    png.unlink()
    assert not png.exists(), "contract: deleting the artifact must break verification"


def test_missing_monid_key_surfaces_as_capability_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import forced_alignment

    async def fake_align(*, audio_path: Path, text: str, **kwargs):
        raise monid_client.MonidError("MONID_API_KEY is not set")

    monkeypatch.setattr(forced_alignment, "forced_align_words", fake_align)

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFFfake")
    cap = caps.get("audio.forced_align")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"audio_path": str(audio), "text": "x"},
            tmp_path / "out2",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
