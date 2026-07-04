"""SaaS-4 回归:出片链的容错/降级与提速(item 3 / item 5)。

这些测试通过 patch omodul 的 agentic_longvideo_pipeline 为"假 omodul":它从传入
的 _providers 里取出 hevi 注入的 audio_fn / video_fn,并**按真实 omodul 的调用方式**
触发它们,从而在不跑云/GPU 的前提下验证注入闭包的真实行为:

  item 3 — 音频合成失败 → 降级为纯视频出片(不落 audio.wav、不抛异常拖垮整任务)。
  item 5 — "short" 单变体:同镜头第二变体(_v1)复用 _v0,省一半生成调用。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from omodul.agentic_longvideo_pipeline import LongVideoResult

from hevi.pipeline.longvideo_orchestrator import orchestrate_longvideo
from hevi.providers.registry import ProviderRegistry, register_all_providers


@pytest.fixture(autouse=True)
def _providers():
    register_all_providers()
    yield


def _line(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, speaker_id="host", voice_ref=None)


@pytest.mark.asyncio
async def test_audio_failure_degrades_to_video_only(tmp_path):
    """TTS provider 抛异常 → injected_audio_fn 吞掉、不落 audio.wav、整任务不失败。"""

    # 注册一个必失败的音频 provider(模拟 vibevoice 模型缺失 / edge-tts 断网)。
    async def failing_audio(**kwargs):
        raise RuntimeError("TTS unavailable (simulated)")

    ProviderRegistry.register("audio", "edge_tts", failing_audio, replace=True)

    out_dir = tmp_path / "task"
    audio_path = out_dir / "audio.wav"

    async def fake_pipeline(*, config, _providers):
        # 复刻 omodul:调用注入的 audio_fn(它内部调失败的 provider)。
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_fn = _providers["audio_fn"]
        # 关键断言:audio_fn 不得抛异常(降级而非崩溃)。
        await audio_fn(script=[_line("你好世界")], output_path=audio_path)
        # 复刻装配:产出一个合法(>1024B)的成片。
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=10.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        res = await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="edge_tts",
            output_dir=out_dir,
        )

    # 任务成功返回;audio.wav 不存在(→ 装配器走纯视频路径)。
    assert res["duration"] == 10.0
    assert not audio_path.exists()


@pytest.mark.asyncio
async def test_character_reference_locks_i2v(tmp_path):
    """角色库:传入 character_reference → 每个镜头都以其做 i2v 参考(锁定身份)。"""
    char_photo = tmp_path / "hero.jpg"
    char_photo.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")  # 文件需存在(orchestrator 校验)
    seen: list[dict] = []

    async def capturing_video(**kwargs):
        seen.append({"reference_image": kwargs.get("reference_image"), "mode": kwargs.get("mode")})
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", capturing_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
        # omodul 会传 reference_image=None(无角色锁定时的逐镜头帧);角色锁定应覆盖它。
        await vfn(prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None)
        vp = tmp_path / "task" / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="英雄跳舞",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            character_reference=str(char_photo),
        )

    assert seen, "video_fn 未被调用"
    # 每次生成都以角色照片做 i2v 参考(而非 omodul 的 None)。
    assert seen[0]["reference_image"] == char_photo
    assert seen[0]["mode"] == "i2v"


@pytest.mark.asyncio
async def test_progress_cb_reports_stages(tmp_path):
    """SaaS-4:各注入阶段应通过 progress_cb 上报步骤文案 + 百分比(供 SSE 显示)。"""
    events: list[tuple[str, float]] = []

    async def progress_cb(stage, pct, completed=None, total=None):
        events.append((stage, pct))

    async def counting_video(**kwargs):
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    async def failing_audio(**kwargs):  # 触发 audio 阶段上报后降级
        raise RuntimeError("no tts")

    ProviderRegistry.register("video", "ltx2_cloud", counting_video, replace=True)
    ProviderRegistry.register("audio", "edge_tts", failing_audio, replace=True)

    out_dir = tmp_path / "task"
    shots = out_dir / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        await _providers["video_fn"](
            prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None
        )
        await _providers["audio_fn"](script=[_line("你好")], output_path=out_dir / "audio.wav")
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=10.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="edge_tts",
            output_dir=out_dir,
            progress_cb=progress_cb,
        )

    stages = [s for s, _ in events]
    assert "准备生成" in stages
    assert any(s == "生成第 1 个镜头" for s in stages)
    assert "合成配音旁白" in stages
    # 百分比应随阶段递增(准备 < 镜头 < 配音)。
    pcts = [p for _, p in events]
    assert pcts == sorted(pcts)


@pytest.mark.asyncio
async def test_short_single_variant_reuses_v0(tmp_path):
    """item 5:short 档下同镜头 _v1 复用 _v0,provider 只被真正调用一次。"""
    calls = {"n": 0}

    async def counting_video(**kwargs):
        calls["n"] += 1
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)  # >1024 视为真实成片
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", counting_video, replace=True)

    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
        # 复刻 omodul 每镜头两变体调用(v0 → v1)。
        await vfn(prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None)
        await vfn(prompt="p", output_path=shots / "shot_0000_v1.mp4", reference_image=None)
        vp = tmp_path / "task" / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=10.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
        )

    # v0 真实生成一次;v1 复用 v0 → provider 仅被调用 1 次,两文件都存在且等大。
    assert calls["n"] == 1
    assert (shots / "shot_0000_v0.mp4").exists()
    assert (shots / "shot_0000_v1.mp4").exists()
    assert (shots / "shot_0000_v0.mp4").stat().st_size == (
        shots / "shot_0000_v1.mp4"
    ).stat().st_size


@pytest.mark.asyncio
async def test_character_voices_maps_matching_speaker_id(tmp_path):
    """character_voices 尽力而为映射:speaker_id 命中 → 换成该角色声音参考(vibevoice);
    没命中(如 LLM 没按约定用 speaker_0/1)→ 保留原样,不报错。"""
    voice_a = tmp_path / "voice_a.wav"
    voice_a.write_bytes(b"RIFF")
    seen: list[dict] = []

    async def capturing_audio(**kwargs):
        for line in kwargs["script"]:
            seen.append({"speaker_id": line.speaker_id, "voice_ref": line.voice_ref})
        Path(kwargs["output_path"]).write_bytes(b"\x00" * 64)

    ProviderRegistry.register("audio", "vibevoice", capturing_audio, replace=True)
    out_dir = tmp_path / "task"

    async def fake_pipeline(*, config, _providers):
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_fn = _providers["audio_fn"]
        script = [
            SimpleNamespace(speaker_id="speaker_0", text="你好", voice_ref=None),  # 命中映射
            SimpleNamespace(speaker_id="speaker_9", text="旁白", voice_ref=None),  # 未命中,保留原样
        ]
        await audio_fn(script=script, output_path=out_dir / "audio.wav")
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp, duration_s=5.0, chapters=1, shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "vibevoice"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            output_dir=out_dir,
            character_voices={"speaker_0": str(voice_a)},
        )

    assert seen[0] == {"speaker_id": "speaker_0", "voice_ref": str(voice_a)}
    assert seen[1] == {"speaker_id": "speaker_9", "voice_ref": None}


@pytest.mark.asyncio
async def test_character_voices_ignored_for_edge_tts(tmp_path):
    """character_voices 仅 vibevoice 生效;edge_tts 时脚本原样透传,不做任何改写。"""
    seen: list[dict] = []

    async def capturing_audio(**kwargs):
        for line in kwargs["script"]:
            seen.append({"speaker_id": getattr(line, "speaker_id", None)})
        Path(kwargs["output_path"]).write_bytes(b"\x00" * 64)

    ProviderRegistry.register("audio", "edge_tts", capturing_audio, replace=True)
    out_dir = tmp_path / "task"

    async def fake_pipeline(*, config, _providers):
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_fn = _providers["audio_fn"]
        await audio_fn(
            script=[SimpleNamespace(speaker_id="speaker_0", text="hi", voice_ref=None)],
            output_path=out_dir / "audio.wav",
        )
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp, duration_s=5.0, chapters=1, shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="edge_tts",
            output_dir=out_dir,
            character_voices={"speaker_0": "/some/voice.wav"},
        )
    assert seen == [{"speaker_id": "speaker_0"}]  # 未被 character_voices 逻辑触碰


@pytest.mark.asyncio
async def test_extra_negative_merges_into_per_shot_negative(tmp_path):
    """extra_negative(角色专属负向)并入每镜负向提示,随 style_preset 的负向一起下发。"""
    seen: list[str | None] = []

    async def capturing_video(**kwargs):
        seen.append(kwargs.get("negative_prompt"))
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "wan_local", capturing_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
        await vfn(prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None)
        vp = tmp_path / "task" / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp, duration_s=5.0, chapters=1, shots_generated=1,
            provider_used={"video": "wan_local", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="wan_local",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            extra_negative="避免多指",
        )

    assert seen, "video_fn 未被调用"
    assert "避免多指" in (seen[0] or "")
