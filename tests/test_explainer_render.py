from __future__ import annotations

from pathlib import Path

import pytest

import hevi.explainer.render as render


@pytest.mark.asyncio
async def test_remotion_render_reports_missing_runtime(monkeypatch, tmp_path: Path):
    missing_dir = tmp_path / "hevi-remotion"
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", missing_dir)
    monkeypatch.setattr(render, "_REMOTION_BIN", missing_dir / "node_modules" / ".bin" / "remotion")

    with pytest.raises(render.RenderError, match="Remotion 项目目录不存在"):
        await render._run_remotion_render("Explainer-Portrait", tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_remotion_render_reports_missing_cli(monkeypatch, tmp_path: Path):
    remotion_dir = tmp_path / "hevi-remotion"
    remotion_dir.mkdir()
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", remotion_dir)
    monkeypatch.setattr(
        render, "_REMOTION_BIN", remotion_dir / "node_modules" / ".bin" / "remotion"
    )

    with pytest.raises(render.RenderError, match="Remotion CLI 不可用"):
        await render._run_remotion_render("Explainer-Portrait", tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_remotion_render_resolves_output_outside_remotion_cwd(monkeypatch, tmp_path: Path):
    remotion_dir = tmp_path / "hevi-remotion"
    remotion_dir.mkdir()
    remotion_bin = remotion_dir / "node_modules" / ".bin" / "remotion"
    remotion_bin.parent.mkdir(parents=True)
    remotion_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    output_root = tmp_path / "output"
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", remotion_dir)
    monkeypatch.setattr(render, "_REMOTION_BIN", remotion_bin)

    captured: dict[str, object] = {}

    class _Process:
        returncode = 0

        async def communicate(self):
            return b"", None

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _Process()

    monkeypatch.setattr(render.asyncio, "create_subprocess_exec", fake_exec)
    await render._run_remotion_render("Explainer-Portrait", output_root / "portrait.mp4")

    args = captured["args"]
    assert isinstance(args, tuple)
    assert Path(args[3]).is_absolute()
    assert captured["kwargs"]["cwd"] == str(remotion_dir)


@pytest.mark.asyncio
async def test_lux_narration_renders_with_cpu_fallback_when_remotion_cli_missing(monkeypatch):
    import math
    import struct
    import subprocess
    import uuid
    import wave

    from hevi.explainer import render
    from hevi.explainer.schemas import ManifestSegment, Storyboard, StoryboardSegment

    root = Path(__file__).resolve().parents[1] / ".tmp" / f"lux-render-fallback-test-{uuid.uuid4().hex[:10]}"
    public = root / "public"
    monkeypatch.setattr(render, "_PUBLIC_DIR", public)
    monkeypatch.setattr(render, "_HEVI_REMOTION_DIR", root / "missing-remotion")
    monkeypatch.setattr(render, "_REMOTION_BIN", root / "missing-remotion" / "node_modules" / ".bin" / "remotion")
    monkeypatch.setattr(render, "_attach_procedural_bgm", lambda *_args, **_kwargs: None)

    async def fake_synthesize_storyboard(
        storyboard, audio_dir, *, voice, rate, audio_public_prefix, provider
    ):
        audio_dir.mkdir(parents=True, exist_ok=True)
        cue_audio = audio_dir / "cue-1.wav"
        sample_rate = 48000
        with wave.open(str(cue_audio), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(sample_rate)
            frames = b"".join(
                struct.pack("<h", int(900 * math.sin(2 * math.pi * 440 * i / sample_rate)))
                for i in range(sample_rate)
            )
            out.writeframes(frames)
        return [
            ManifestSegment(
                id="cue-1",
                scene_type="hook",
                text="小兔子你好呀。我们一起去看花吧！",
                audio_file=f"{audio_public_prefix}/cue-1.wav",
                duration_sec=1.0,
                start_sec=0.0,
                keywords=["小兔子", "花"],
                props={"title": "小兔子你好呀", "subtitle": "一起去看花", "items": []},
                captions=[],
            )
        ]

    monkeypatch.setattr(render, "synthesize_storyboard", fake_synthesize_storyboard)
    storyboard = Storyboard(
        topic="小兔子的奇妙花园",
        segments=[
            StoryboardSegment(
                id="cue-1",
                scene_type="hook",
                narration="小兔子你好呀。我们一起去看花吧！",
                props={"title": "小兔子你好呀", "subtitle": "一起去看花", "items": []},
            )
        ],
    )
    output_dir = root / "output"
    result = await render.render_storyboard(storyboard, output_dir, tts_provider="lux_tts")

    assert result.render_runtime == "ffmpeg"
    assert result.portrait_path.is_file() and result.portrait_path.stat().st_size > 0
    assert result.landscape_path.is_file() and result.landscape_path.stat().st_size > 0
    for path, expected_size in ((result.portrait_path, (540, 960)), (result.landscape_path, (960, 540))):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        import json
        payload = json.loads(probe.stdout)
        streams = payload["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        assert (video["width"], video["height"]) == expected_size
        assert any(stream["codec_type"] == "audio" for stream in streams)
        assert 3.6 <= float(payload["format"]["duration"]) <= 4.4
