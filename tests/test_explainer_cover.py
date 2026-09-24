from __future__ import annotations

from pathlib import Path

import pytest

from hevi.explainer.cover import cover_extract_and_render


@pytest.mark.asyncio
async def test_cover_fallback_records_hevi_local_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    out = tmp_path / "cover.jpg"

    def fake_extract(input_video: Path, output_path: Path, timestamp: float = 0.5) -> Path:
        assert input_video == video
        output_path.write_bytes(b"jpegdata")
        return output_path

    import hevi.explainer.cover as cover_mod

    monkeypatch.setattr(
        "hevi.assembly.cover_extractor.extract_cover",
        fake_extract,
        raising=False,
    )
    # Force ImportError on oprim path by making import fail
    import builtins

    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "oprim" or name.startswith("oprim."):
            raise ImportError("oprim cover extractor unavailable")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    envelope = await cover_extract_and_render(video, out, title="t")
    assert envelope["status"] == "succeeded"
    assert envelope["path"] == str(out)
    assert envelope["requested_extractor"] == "oprim"
    assert envelope["actual_extractor"] == "hevi_local"
    assert envelope["extractor_substituted"] is True
    assert str(envelope["fallback_reason"]).startswith("oprim_unavailable:")
    assert cover_mod is not None


@pytest.mark.asyncio
async def test_cover_injected_extractor_is_not_substituted(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    out = tmp_path / "cover.jpg"

    def fake(video_path: Path, output_path: Path) -> Path:
        output_path.write_bytes(b"jpeg")
        return output_path

    envelope = await cover_extract_and_render(video, out, extractor=fake)
    assert envelope["status"] == "succeeded"
    assert envelope["requested_extractor"] == "injected"
    assert envelope["actual_extractor"] == "injected"
    assert envelope["extractor_substituted"] is False
    assert "fallback_reason" not in envelope


@pytest.mark.asyncio
async def test_cover_failure_still_returns_provenance(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    out = tmp_path / "cover.jpg"

    def boom(video_path: Path, output_path: Path) -> Path:
        raise RuntimeError("ffmpeg died")

    envelope = await cover_extract_and_render(video, out, extractor=boom)
    assert envelope["status"] == "failed"
    assert "ffmpeg died" in str(envelope["error"])
    assert envelope["requested_extractor"] == "injected"
    assert envelope["actual_extractor"] == "injected"
    assert envelope["extractor_substituted"] is False
