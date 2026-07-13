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
from unittest.mock import AsyncMock, patch

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
async def test_style_reference_image_conditions_happyhorse_lock(tmp_path):
    """SPEC-002 B2:video_provider 恰好是 happyhorse_1_1_maas_lock 时,style_reference_image
    才会被塞进 provider kwargs(该 provider 支持 2 张参考图,做真实图片条件化)。"""
    char_photo = tmp_path / "hero.jpg"
    char_photo.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    style_photo = tmp_path / "style.jpg"
    style_photo.write_bytes(b"\xff\xd8\xff\xe0fakestyle")
    seen: list[dict] = []

    async def capturing_video(**kwargs):
        seen.append(
            {
                "reference_image": kwargs.get("reference_image"),
                "style_reference_image": kwargs.get("style_reference_image"),
            }
        )
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "happyhorse_1_1_maas_lock", capturing_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
        await vfn(prompt="p", output_path=shots / "shot_0000_v0.mp4", reference_image=None)
        vp = tmp_path / "task" / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "happyhorse_1_1_maas_lock", "audio": "edge_tts"},
        )

    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
        side_effect=fake_pipeline,
    ):
        await orchestrate_longvideo(
            topic="英雄跳舞",
            duration_archetype="short",
            video_provider="happyhorse_1_1_maas_lock",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            character_reference=str(char_photo),
            style_reference_image=str(style_photo),
        )

    assert seen, "video_fn 未被调用"
    assert seen[0]["reference_image"] == char_photo
    assert seen[0]["style_reference_image"] == style_photo


@pytest.mark.asyncio
async def test_style_reference_image_ignored_for_other_providers(tmp_path):
    """SPEC-002 B2:非 happyhorse_1_1_maas_lock 的 provider 不认识 style_reference_image,
    orchestrator 不会把它塞进 kwargs——零回归,不会撞 unexpected keyword argument。"""
    char_photo = tmp_path / "hero.jpg"
    char_photo.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    style_photo = tmp_path / "style.jpg"
    style_photo.write_bytes(b"\xff\xd8\xff\xe0fakestyle")
    seen: list[dict] = []

    async def capturing_video(*, prompt, output_path, reference_image=None, mode=None, **kw):
        # 严格签名(不带 **kw 兜底 style_reference_image)——模拟 ltx2_cloud 这类不认识
        # 这个新 kwarg 的 provider,如果 orchestrator 误传就会在这里直接 TypeError。
        assert "style_reference_image" not in kw
        seen.append({"reference_image": reference_image})
        outp = Path(output_path)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", capturing_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
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
            style_reference_image=str(style_photo),
        )

    assert seen, "video_fn 未被调用"
    assert seen[0]["reference_image"] == char_photo


@pytest.mark.asyncio
async def test_shot_keyframes_routes_matched_shot_to_keyframe_provider(tmp_path):
    """SPEC-002 B3:shot_keyframes 命中的镜头(索引对得上 + 首尾帧文件都存在)整个绕开
    正常的单图 i2v caller,直接走首尾帧生视频——不会同时调用两条路径。"""
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    first.write_bytes(b"\xff\xd8\xff\xe0first")
    last.write_bytes(b"\xff\xd8\xff\xe0last")

    normal_caller_calls: list[dict] = []

    async def normal_video(**kwargs):
        normal_caller_calls.append(kwargs)
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", normal_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
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

    fake_kf = AsyncMock(side_effect=lambda **kw: _write_and_return(kw["output_path"]))
    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.video.alibaba_maas_service.alibaba_maas_keyframe_lock_generate", fake_kf),
    ):
        await orchestrate_longvideo(
            topic="英雄跳舞",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            shot_keyframes={0: {"first_frame": str(first), "last_frame": str(last)}},
        )

    fake_kf.assert_awaited_once()
    assert fake_kf.await_args.kwargs["first_frame"] == first
    assert fake_kf.await_args.kwargs["last_frame"] == last
    assert not normal_caller_calls, "命中 shot_keyframes 的镜头不该再走正常 i2v caller"


@pytest.mark.asyncio
async def test_shot_keyframes_string_keys_from_jsonb_roundtrip_still_match(tmp_path):
    """SPEC-002 B3:config_json 走 JSONB 落库/回读,dict key 只能是字符串——
    shot_keyframes={"0": {...}}(而非 int key 0)也必须命中同一个镜头。"""
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    first.write_bytes(b"\xff\xd8\xff\xe0first")
    last.write_bytes(b"\xff\xd8\xff\xe0last")

    async def normal_video(**kwargs):
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", normal_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
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

    fake_kf = AsyncMock(side_effect=lambda **kw: _write_and_return(kw["output_path"]))
    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.video.alibaba_maas_service.alibaba_maas_keyframe_lock_generate", fake_kf),
    ):
        await orchestrate_longvideo(
            topic="英雄跳舞",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            shot_keyframes={"0": {"first_frame": str(first), "last_frame": str(last)}},
        )

    fake_kf.assert_awaited_once()


@pytest.mark.asyncio
async def test_shot_keyframes_missing_files_falls_back_to_normal_generation(tmp_path):
    """SPEC-002 B3:shot_keyframes 里的首尾帧文件不存在 → 优雅回退正常单图 i2v,不阻断镜头。"""
    normal_caller_calls: list[dict] = []

    async def normal_video(**kwargs):
        normal_caller_calls.append(kwargs)
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", normal_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
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
            shot_keyframes={
                0: {"first_frame": "/nonexistent/first.png", "last_frame": "/nonexistent/last.png"}
            },
        )

    assert normal_caller_calls, "首尾帧文件缺失时应回退正常 i2v caller"


@pytest.mark.asyncio
async def test_shot_keyframes_generation_failure_falls_back_to_normal_generation(tmp_path):
    """SPEC-002 B3:首尾帧生视频调用失败(如 provider 报错)→ 优雅回退正常单图 i2v。"""
    first = tmp_path / "first.png"
    last = tmp_path / "last.png"
    first.write_bytes(b"\xff\xd8\xff\xe0first")
    last.write_bytes(b"\xff\xd8\xff\xe0last")
    normal_caller_calls: list[dict] = []

    async def normal_video(**kwargs):
        normal_caller_calls.append(kwargs)
        outp = Path(kwargs["output_path"])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"\x00" * 4096)
        return outp

    ProviderRegistry.register("video", "ltx2_cloud", normal_video, replace=True)
    shots = tmp_path / "task" / "shots"

    async def fake_pipeline(*, config, _providers):
        shots.mkdir(parents=True, exist_ok=True)
        vfn = _providers["video_fn"]
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

    fake_kf = AsyncMock(side_effect=RuntimeError("kf2v provider error (simulated)"))
    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.video.alibaba_maas_service.alibaba_maas_keyframe_lock_generate", fake_kf),
    ):
        await orchestrate_longvideo(
            topic="英雄跳舞",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="ltx2_native",
            output_dir=tmp_path / "task",
            shot_keyframes={0: {"first_frame": str(first), "last_frame": str(last)}},
        )

    fake_kf.assert_awaited_once()
    assert normal_caller_calls, "首尾帧生成失败后应回退正常 i2v caller"


def _write_and_return(output_path) -> Path:
    outp = Path(output_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_bytes(b"\x00" * 4096)
    return outp


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
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
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
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="edge_tts",
            output_dir=out_dir,
            character_voices={"speaker_0": "/some/voice.wav"},
        )
    assert seen == [{"speaker_id": "speaker_0"}]  # 未被 character_voices 逻辑触碰


@pytest.mark.asyncio
async def test_emotion_aware_voiceover_derives_per_line_emotion(tmp_path):
    """SPEC-002 B1:emotion_aware_voiceover=True + edge_tts → 台词批量推断情绪,
    每行包上 .emotion 属性传给 synthesize_with_voice_control。"""
    out_dir = tmp_path / "task"
    seen_scripts: list[list] = []

    async def fake_synthesize(*, config, script, output_path, **kw):
        seen_scripts.append(list(script))
        Path(output_path).write_bytes(b"\x00" * 64)
        return Path(output_path)

    async def fake_pipeline(*, config, _providers):
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_fn = _providers["audio_fn"]
        script = [
            SimpleNamespace(speaker_id="C001", text="要地予我", voice_ref=None),
            SimpleNamespace(speaker_id="NARRATOR", text="三家终于罢兵", voice_ref=None),
        ]
        await audio_fn(script=script, output_path=out_dir / "audio.wav")
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.audio.edge_tts_custom.synthesize_with_voice_control", fake_synthesize),
        patch(
            "hevi.prompt.emotion_inference.infer_line_emotions",
            AsyncMock(return_value=["倨傲", "平静"]),
        ) as mock_infer,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="edge_tts",
            output_dir=out_dir,
            emotion_aware_voiceover=True,
        )

    mock_infer.assert_awaited_once_with(["要地予我", "三家终于罢兵"])
    assert seen_scripts, "audio caller 未被调用"
    got = seen_scripts[0]
    assert [ln.emotion for ln in got] == ["倨傲", "平静"]
    assert [ln.text for ln in got] == ["要地予我", "三家终于罢兵"]


@pytest.mark.asyncio
async def test_emotion_aware_voiceover_disabled_by_default(tmp_path):
    """默认关(opt-in),零行为变化:不推断情绪,不走 synthesize_with_voice_control,
    script 原样透传给 registry 默认 provider——跟没有这个开关时完全一样。"""
    out_dir = tmp_path / "task"
    seen: list[dict] = []

    async def capturing_audio(**kwargs):
        for line in kwargs["script"]:
            seen.append({"has_emotion": hasattr(line, "emotion")})
        Path(kwargs["output_path"]).write_bytes(b"\x00" * 64)

    ProviderRegistry.register("audio", "edge_tts", capturing_audio, replace=True)

    async def fake_pipeline(*, config, _providers):
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_fn = _providers["audio_fn"]
        await audio_fn(
            script=[SimpleNamespace(speaker_id="host", text="hi", voice_ref=None)],
            output_path=out_dir / "audio.wav",
        )
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.prompt.emotion_inference.infer_line_emotions", AsyncMock()) as mock_infer,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="edge_tts",
            output_dir=out_dir,
            # emotion_aware_voiceover 未传 → 默认 False
        )

    mock_infer.assert_not_awaited()
    assert seen == [{"has_emotion": False}]


@pytest.mark.asyncio
async def test_emotion_aware_voiceover_ignored_for_vibevoice(tmp_path):
    """仅 edge_tts 生效——vibevoice 没有 rate/pitch 概念,开关对它没意义,不触发推断。"""
    out_dir = tmp_path / "task"

    async def capturing_audio(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"\x00" * 64)

    ProviderRegistry.register("audio", "vibevoice", capturing_audio, replace=True)

    async def fake_pipeline(*, config, _providers):
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_fn = _providers["audio_fn"]
        await audio_fn(
            script=[SimpleNamespace(speaker_id="host", text="hi", voice_ref=None)],
            output_path=out_dir / "audio.wav",
        )
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "vibevoice"},
        )

    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.prompt.emotion_inference.infer_line_emotions", AsyncMock()) as mock_infer,
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
            output_dir=out_dir,
            emotion_aware_voiceover=True,
        )

    mock_infer.assert_not_awaited()


@pytest.mark.asyncio
async def test_emotion_aware_voiceover_inference_failure_degrades_gracefully(tmp_path):
    """情绪推断异常(而非 infer_line_emotions 自身的 best-effort 返回空)→ 不阻断配音,
    整批退化为空情绪(等同没开这个开关)。"""
    out_dir = tmp_path / "task"
    seen_scripts: list[list] = []

    async def fake_synthesize(*, config, script, output_path, **kw):
        seen_scripts.append(list(script))
        Path(output_path).write_bytes(b"\x00" * 64)
        return Path(output_path)

    async def fake_pipeline(*, config, _providers):
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_fn = _providers["audio_fn"]
        await audio_fn(
            script=[SimpleNamespace(speaker_id="host", text="hi", voice_ref=None)],
            output_path=out_dir / "audio.wav",
        )
        vp = out_dir / "final.mp4"
        vp.write_bytes(b"\x00" * 2048)
        return LongVideoResult(
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
            provider_used={"video": "ltx2_cloud", "audio": "edge_tts"},
        )

    with (
        patch(
            "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline",
            side_effect=fake_pipeline,
        ),
        patch("hevi.audio.edge_tts_custom.synthesize_with_voice_control", fake_synthesize),
        patch(
            "hevi.prompt.emotion_inference.infer_line_emotions",
            AsyncMock(side_effect=RuntimeError("llm down")),
        ),
    ):
        await orchestrate_longvideo(
            topic="t",
            duration_archetype="short",
            video_provider="ltx2_cloud",
            audio_provider="edge_tts",
            output_dir=out_dir,
            emotion_aware_voiceover=True,
        )

    assert seen_scripts, "audio caller 未被调用(推断失败不该阻断配音)"
    assert [ln.emotion for ln in seen_scripts[0]] == [""]


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
            video_path=vp,
            duration_s=5.0,
            chapters=1,
            shots_generated=1,
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
