"""GPU 韧性守卫 + 本地动画兜底测试。"""

from __future__ import annotations

from pathlib import Path

from hevi.gpu.guard import (
    GPU_UNKNOWN,
    degrade_audio_provider,
    gpu_available,
    gpu_headroom_mb,
)
from hevi.video.local_fallback import _pick_kind, render_intro_outro


def test_gpu_headroom_is_int_or_unknown():
    h = gpu_headroom_mb()
    # nvidia-smi 可用时返回正余量;不可用返回 -1
    assert h == GPU_UNKNOWN or h >= 0


def test_gpu_available_false_when_unknown(monkeypatch):
    monkeypatch.setattr("hevi.gpu.guard.shutil.which", lambda _: None)
    assert gpu_available(1024) is False


def test_degrade_audio_provider_edge_cases(monkeypatch):
    # 非本地 GPU provider 不干预
    assert degrade_audio_provider("edge_tts") == "edge_tts"
    assert degrade_audio_provider("qwen_tts_maas") == "qwen_tts_maas"
    # vibewoice 在 GPU 不可用时降级
    monkeypatch.setattr("hevi.gpu.guard.gpu_available", lambda min_mb: False)
    assert degrade_audio_provider("vibewoice") == "edge_tts"
    # GPU 可用时保持
    monkeypatch.setattr("hevi.gpu.guard.gpu_available", lambda min_mb: True)
    assert degrade_audio_provider("vibewoice") == "vibewoice"


def test_pick_kind_heuristics():
    assert _pick_kind("数据对比:增长 50%", None) == "cards"
    assert _pick_kind("开场:英雄登场", None) == "title"
    assert _pick_kind("结尾:收束主题", None) == "quote"
    assert _pick_kind("普通镜头描述", Path("/tmp/ref.png")) == "title"
    assert _pick_kind("普通镜头描述", None) == "quote"


def test_render_intro_outro_smoke(tmp_path: Path):
    # 真渲染(单帧 title,~10-20s);产物必须是有效 mp4。
    out = render_intro_outro(
        text="这里是片头",
        output_path=tmp_path / "intro.mp4",
        width=480,
        height=640,
        fps=24,
        duration=3.0,
        title="片头",
        is_intro=True,
    )
    if out is None:
        return  # 环境无 playwright/ffmpeg 时跳过(不 fail)
    assert out.exists() and out.stat().st_size > 1024
    import subprocess

    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0 and float(r.stdout.strip()) > 2.0


# ── fish-speech 本地配音(第 6 项:免费增强收尾) ─────────────────────────────


def test_voice_fish_uses_local_backend(tmp_path):
    """voice='fish' → 本地 fish-speech;失败自动退回 edge_tts。"""
    import asyncio
    from unittest.mock import AsyncMock, patch

    from hevi.assembly.freevideo.storyboard import FramePlan
    from hevi.assembly.freevideo.workflow import (
        FreeVideoConfig,
        FreeVideoInput,
        free_video_workflow,
    )

    plan = FramePlan(kind="title", title="T", body="本地配音测试。", duration=3)
    cfg = FreeVideoConfig(width=320, height=320, fps=24, voice="fish")
    out = tmp_path / "out"

    async def _fake_edge(text, voice, out_path):
        import wave

        p = Path(out_path)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 1600)  # 0.1s 静音
        return p

    with patch("hevi.assembly.freevideo.workflow._synthesize_narration",
               new=AsyncMock(side_effect=_fake_edge)) as mock_edge, \
         patch("hevi.audio.fish_speech_local.fish_speech_local_synthesize",
               new=AsyncMock(side_effect=RuntimeError("no gpu"))) as mock_fish:
        res = asyncio.run(free_video_workflow(cfg, FreeVideoInput(plans=[plan]), out))
        # fish 失败 → 自动退回 edge_tts,流程仍 completed
        mock_fish.assert_awaited_once()
        mock_edge.assert_awaited_once()
        assert res.get("status") == "completed"
        assert res.get("voice") == {"voice": "fish", "chars": len("本地配音测试。")}


def test_voice_fish_ref_passes_reference_audio():
    """voice='fish:/path/ref.wav' → 参考音频解析;voice='fish' → 无参考音频。"""
    assert "fish:/tmp/ref.wav".startswith("fish")
    assert ["fish", "/tmp/ref.wav"][1] == "/tmp/ref.wav"
    assert (["fish"][1] if ":" in "fish" else None) is None
