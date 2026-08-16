"""post pipeline 单测 —— raw → final(降级纪律:超分/插帧失败不卡 raw)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.post.pipeline import PostResult, run_post_pipeline


def _make_clip(path: Path, seconds: float = 2.0, with_audio: bool = True) -> Path:
    """lavfi 合成片(真 ffmpeg):testsrc + 可选 sine 音轨。"""
    import subprocess

    path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={seconds}:size=320x180:rate=24",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        args += ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-c:a", "aac"]
    else:
        args += ["-an", "-c:v", "libx264"]
    args.append(str(path))
    subprocess.run(args, check=True, capture_output=True, timeout=60)
    return path


@pytest.mark.asyncio
async def test_pipeline_off_off_copies_raw(tmp_path: Path) -> None:
    raw = _make_clip(tmp_path / "raw.mp4")
    final = tmp_path / "shots" / "001" / "final.mp4"
    result: PostResult = await run_post_pipeline(
        raw, final, config={"upscale": "off", "interp": "off"}
    )
    assert final.exists() and final.stat().st_size > 1024
    assert result.upscaled is False
    assert result.interpolated is False
    assert result.fps_out == 24
    post_json = json.loads(final.with_suffix(final.suffix + ".post.json").read_text())
    assert post_json["fps_out"] == 24
    assert post_json["upscaled"] is False


@pytest.mark.asyncio
async def test_pipeline_interp_unavailable_degrades_with_no_interp(tmp_path: Path) -> None:
    """vspipe 装了但无 RIFE 插件(方案 B 核心不可用)→ 标记 no_interp 降级交付,不抛错。"""
    import shutil

    raw = _make_clip(tmp_path / "raw.mp4")
    final = tmp_path / "final.mp4"
    result = await run_post_pipeline(
        raw,
        final,
        config={
            "upscale": "off",
            "interp": "rife2x",
            "rife": {"engine": "vspipe"},  # 钉死 vspipe,不触发 comfy_vfi 自动探测
        },
    )
    assert final.exists()
    if shutil.which("vspipe") is None:
        assert "no_interp" in result.notes
        assert result.interpolated is False
        assert result.fps_out == 24
    else:
        # vspipe 在但无 RIFE 插件 → 脚本执行失败 → 同样降级 no_interp
        assert "no_interp" in result.notes
        assert result.interpolated is False
        assert result.fps_out == 24


@pytest.mark.asyncio
async def test_pipeline_upscale_unavailable_degrades_to_raw(tmp_path: Path) -> None:
    """本机没有 FlashVSR 节点 → FlashVSRUnavailable → 降级用 raw 继续。"""
    from hevi.post.flashvsr import FlashVSRUnavailable, require_nodes
    from hevi.providers.h3_local.comfy_client import ComfyClient

    client = ComfyClient(base_url="http://127.0.0.1:1", serial=False)  # 不可达
    with pytest.raises(FlashVSRUnavailable):
        await require_nodes(client, ("FlashVSRInitPipe",))

    raw = _make_clip(tmp_path / "raw.mp4")
    final = tmp_path / "final.mp4"
    result = await run_post_pipeline(
        raw, final, config={"upscale": "flashvsr", "interp": "off"}, comfy_client=client
    )
    assert final.exists()
    assert result.upscaled is False
    assert any("upscale_skipped" in n for n in result.notes)


@pytest.mark.asyncio
async def test_pipeline_missing_input_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await run_post_pipeline(
            tmp_path / "nope.mp4",
            tmp_path / "final.mp4",
            config={"upscale": "off", "interp": "off"},
        )


@pytest.mark.asyncio
async def test_pipeline_invalid_modes_raise(tmp_path: Path) -> None:
    raw = _make_clip(tmp_path / "raw.mp4")
    with pytest.raises(ValueError):
        await run_post_pipeline(raw, tmp_path / "f.mp4", config={"upscale": "bogus"})
    with pytest.raises(ValueError):
        await run_post_pipeline(raw, tmp_path / "f.mp4", config={"interp": "bogus"})


@pytest.mark.asyncio
async def test_resolve_engine_falls_back_when_comfy_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto 引擎:ComfyUI 不可达/无 VFI 节点 → 回落 vspipe(装了)或 none。"""
    from hevi.post.rife_vs import _resolve_engine

    async def _no_health(self) -> bool:
        return False

    monkeypatch.setattr("hevi.post.rife_vs.shutil.which", lambda _: "/usr/bin/vspipe")
    monkeypatch.setattr(
        "hevi.providers.h3_local.comfy_client.ComfyClient.health", _no_health
    )
    engine = await _resolve_engine({})
    assert engine == "vspipe"

    # 显式钉死 comfy_vfi:不可达也要它自己报错,不静默换引擎
    engine2 = await _resolve_engine({"engine": "comfy_vfi"})
    assert engine2 == "comfy_vfi"


@pytest.mark.asyncio
async def test_interpolate_rife_no_engine_raises(tmp_path: Path) -> None:
    """engine=none → RifeUnavailable(由 pipeline 转 no_interp 降级)。"""
    from hevi.post.rife_vs import RifeUnavailable, interpolate_rife

    raw = _make_clip(tmp_path / "raw.mp4")
    with pytest.raises(RifeUnavailable):
        await interpolate_rife(raw, tmp_path / "f.mp4", config={"engine": "none"})


def test_rife_vfi_template_builds() -> None:
    """rife_vfi_2x.json 模板:占位符填充 + 节点链完整(纯逻辑,无网络)。"""
    from hevi.providers.h3_local.comfy_client import ComfyClient

    client = ComfyClient(base_url="http://127.0.0.1:1", serial=False)
    wf = client.build_workflow(
        "rife_vfi_2x.json",
        output_prefix="h3_rife_x",
        extra_fills={
            "__VIDEO_PATH__": "/tmp/in.mp4",
            "__RIFE_MODEL__": "rife425.pth",
            "__MULTIPLIER__": 2,
            "__FPS__": 48.0,
        },
        workflows_dir=Path(__file__).resolve().parents[1] / "hevi" / "post" / "workflows",
    )
    assert wf["interp_model"]["inputs"]["model_name"] == "rife425.pth"
    assert wf["rife"]["inputs"]["multiplier"] == 2
    assert wf["save"]["inputs"]["frame_rate"] == 48.0
    assert wf["load"]["inputs"]["video"] == "/tmp/in.mp4"


@pytest.mark.asyncio
async def test_pipeline_audio_mux_from_raw(tmp_path: Path) -> None:
    """off/off + raw 带音轨 → final 应该仍然带音轨(对白轨优先 H3 原音)。"""
    raw = _make_clip(tmp_path / "raw.mp4", with_audio=True)
    final = tmp_path / "final.mp4"
    await run_post_pipeline(raw, final, config={"upscale": "off", "interp": "off"})
    import subprocess

    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(final),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert "audio" in out.stdout
