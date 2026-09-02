"""Behavioral coverage for the provider-neutral HEVI capability contracts.

These tests exercise deterministic planning, validation, provider-unavailable
states, and real local artifact checks.  They never turn an unavailable remote
provider into a successful artifact.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest


def test_visual_asset_planning_and_truthful_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.creative_assets.omodul.runtime import execute_visual_asset, plan_visual_asset
    from hevi.creative_assets.oprim.contracts import VisualAssetRequest
    from hevi.creative_assets.oskill.compiler import compile_visual_prompt, default_aspect_ratio

    missing = VisualAssetRequest(
        kind="unknown", subject="", platform="unknown", reference_path="missing.png"
    )
    blocked = plan_visual_asset(missing)
    assert blocked.status == "blocked" and blocked.errors
    assert default_aspect_ratio("xiaohongshu") == "3:4"
    request = VisualAssetRequest(
        kind="cover",
        subject="a red lantern",
        platform="youtube",
        style="ink",
        negative_prompt="text",
    )
    assert "ink wash" in compile_visual_prompt(request)
    planned = asyncio.run(
        execute_visual_asset(request, output_path=tmp_path / "cover.png", provider="")
    )
    assert planned["status"] == "blocked" and not (tmp_path / "cover.png").exists()
    prompt_only = asyncio.run(
        execute_visual_asset(
            VisualAssetRequest(kind="thumbnail", subject="lantern", prompt_only=True),
            output_path=tmp_path / "prompt.png",
            provider="local",
        )
    )
    assert prompt_only["status"] == "planned" and prompt_only["output_path"] is None

    class Registry:
        @staticmethod
        def image_gen(_name: str):
            async def generate(**kwargs: object) -> dict[str, str]:
                output = kwargs["output_path"]
                assert isinstance(output, Path)
                output.write_bytes(b"real-test-artifact")
                return {"artifact": str(output)}

            return generate

    import obase.provider_registry as registry_module

    monkeypatch.setattr(registry_module.ProviderRegistry, "get", lambda: Registry())
    completed = asyncio.run(
        execute_visual_asset(request, output_path=tmp_path / "completed.png", provider="local")
    )
    assert completed["status"] == "completed"
    assert Path(completed["output_path"]).read_bytes() == b"real-test-artifact"


def test_talkcraft_and_voice_agent_plans_are_explicit() -> None:
    from hevi.talkcraft.omodul.runtime import compile_talkcraft_plan
    from hevi.talkcraft.oprim.contracts import TalkcraftRequest, TalkCue
    from hevi.talkcraft.oskill.compiler import choose_motion_cards
    from hevi.voice_agent.omodul.runtime import compile_voice_pipeline, voice_agent_capabilities
    from hevi.voice_agent.oprim.contracts import VoiceAgentRequest, VoiceStage
    from hevi.voice_agent.oskill.compiler import (
        default_voice_request,
        natural_language_voice_request,
    )

    cue = TalkCue("c1", "hello", 0, 2, speaker="narrator")
    plan = compile_talkcraft_plan(TalkcraftRequest(cues=(cue,)))
    assert plan["status"] == "planned" and plan["cards"]
    assert compile_talkcraft_plan(TalkcraftRequest())["status"] == "blocked"
    assert choose_motion_cards([], card_limit=2) == []
    assert len(choose_motion_cards([{"cue_id": "1", "start_s": 0, "end_s": 1}], card_limit=1)) == 1

    default = default_voice_request()
    assert len(default.stages) == 5
    nl = natural_language_voice_request("用 Voicebox 多智能体并按住说话后粘贴听写")
    assert nl.stages[-1].engine == "multi_agent_router"
    assert nl.stages[3].engine == "voicebox" and nl.hold_to_speak and nl.paste_transcript
    invalid = VoiceAgentRequest(
        transport="websocket",
        paste_transcript=True,
        stages=(VoiceStage("x", "bad", ""), VoiceStage("x", "tts", "tts")),
    )
    blocked = compile_voice_pipeline(invalid)
    assert blocked.status == "blocked" and blocked.errors
    planned = compile_voice_pipeline(default)
    assert planned.status == "planned" and planned.edges[0] == ("mic", "transcribe")
    assert voice_agent_capabilities()["available"] is False


def test_video_catcher_local_and_remote_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import hevi.video_catcher.omodul.runtime as runtime
    from hevi.video_catcher.oprim.contracts import VideoCatchRequest
    from hevi.video_catcher.oskill.compiler import format_selector, select_source_mode

    source = tmp_path / "source.mp4"
    source.write_bytes(b"nonempty")
    monkeypatch.setattr(
        runtime,
        "_probe",
        lambda _path: {
            "verified": True,
            "probe": {
                "format": {"duration": "2.5"},
                "streams": [{"codec_type": "video", "width": 320, "height": 240}],
            },
        },
    )
    request = VideoCatchRequest(source=str(source), quality="720p")
    discovery = runtime.discover_video(request)
    assert discovery.status == "discovered" and discovery.duration_s == 2.5
    local = runtime.download_video(request)
    assert local["status"] == "completed"
    assert format_selector(request).startswith("bestvideo[height<=720]")
    assert select_source_mode(VideoCatchRequest("https://example.test/a.m3u8")) == "manifest"
    assert (
        format_selector(VideoCatchRequest("https://example.test", merge_audio=False))
        == "bestvideo+bestaudio/best"
        or format_selector(VideoCatchRequest("https://example.test", merge_audio=False)) == "best"
    )

    invalid = runtime.discover_video(VideoCatchRequest(source=""))
    assert invalid.status == "blocked"
    monkeypatch.setattr(runtime.shutil, "which", lambda _name: None)
    remote = VideoCatchRequest("https://example.test/video", output_dir=str(tmp_path / "remote"))
    assert runtime.discover_video(remote).status == "blocked"
    assert runtime.download_video(remote)["status"] == "blocked"

    monkeypatch.setattr(runtime.shutil, "which", lambda _name: "/usr/bin/yt-dlp")

    def run_download(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if "--dump-single-json" in command:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "title": "demo",
                        "duration": 3,
                        "width": 640,
                        "height": 360,
                        "formats": [{"format_id": "1", "ext": "mp4", "height": 360}],
                        "subtitles": {"en": []},
                        "extractor": "test",
                        "webpage_url": "https://example.test/video",
                    }
                ),
                stderr="",
            )
        output_dir = Path(command[command.index("-o") + 1]).parent
        output_dir.joinpath("demo.mp4").write_bytes(b"downloaded")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runtime.subprocess, "run", run_download)
    discovered = runtime.discover_video(remote)
    assert discovered.status == "discovered" and discovered.formats[0]["format_id"] == "1"
    downloaded = runtime.download_video(remote)
    assert downloaded["status"] == "completed"
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("yt-dlp", 1)),
    )
    assert (
        runtime.download_video(
            VideoCatchRequest("https://example.test/timeout", output_dir=str(tmp_path / "timeout"))
        )["status"]
        == "failed"
    )


def test_previs_longvideo_and_pipeline_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.longvideo.omodul.runtime import compile_longvideo_plan, longvideo_capabilities
    from hevi.longvideo.oprim.contracts import LongVideoRequest
    from hevi.previs.omodul.runtime import compile_previs_scene
    from hevi.previs.oprim.contracts import CameraCue, CastItem, PrevisScene, TimelineCue
    from hevi.previs.oskill.compiler import camera_from_instruction
    from hevi.production.multimodal_refs import reference_grid
    from hevi.production.pipelines.omodul.runtime import (
        compile_pipeline_request,
        get_pipeline,
        list_pipelines,
    )
    from hevi.production.pipelines.oprim.contracts import PipelineRequest
    from hevi.production.pipelines.oskill.compiler import pipeline_for_brief

    scene = PrevisScene(
        "scene-1",
        "Opening",
        cast=(CastItem("hero", "Hero", pose="walk"),),
        cameras=(CameraCue("cam-1", 0, "wide", "dolly_in", 20),),
        timeline=(TimelineCue("beat-1", 0, 2, "enter"),),
        environment_prompt="studio",
    )
    compiled_scene = compile_previs_scene(scene)
    assert compiled_scene["status"] == "planned" and compiled_scene["scene_stage"][
        "characters"
    ] == ["Hero"]
    assert compile_previs_scene(PrevisScene("", ""))["status"] == "blocked"
    assert camera_from_instruction("远景向右移 45 度").movement == "tracking_right"
    assert camera_from_instruction("特写静止 -10deg").azimuth_deg == -10

    planned = compile_longvideo_plan(LongVideoRequest(prompt="a film", duration_s=12, mode="t2v"))
    assert planned["status"] == "planned"
    monkeypatch.setenv("LONGLIVE_BASE_URL", "http://longlive.local")
    available = compile_longvideo_plan(
        LongVideoRequest(prompt="", mode="multi_shot", shot_prompts=("one", "two"))
    )
    assert available["status"] == "available" and longvideo_capabilities()["available"]
    assert compile_longvideo_plan(LongVideoRequest(prompt="", mode="i2v"))["status"] == "blocked"

    specs = list_pipelines()
    assert (
        len(specs) >= 10
        and get_pipeline("cinematic") is not None
        and get_pipeline("missing") is None
    )
    assert (
        pipeline_for_brief("做一个短剧", [get_pipeline("short_drama")]).pipeline_id == "short_drama"
    )
    valid = compile_pipeline_request(PipelineRequest("cinematic", "a cinematic brief"))
    assert valid["status"] == "planned" and valid["artifact_policy"].startswith("only verified")
    invalid = compile_pipeline_request(
        PipelineRequest("missing", "", images=tuple("x" for _ in range(10)))
    )
    assert invalid["status"] == "blocked" and invalid["errors"]
    assert reference_grid(images=["a", "b"], columns=2)["rows"] == 1
    with pytest.raises(ValueError):
        reference_grid(images=["a"], columns=0)


@pytest.mark.asyncio
async def test_longcat_context_protocol_and_agent_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hevi.longcat.omodul.runtime import (
        LongCatConfig,
        longcat_agent_workflow,
        longcat_capabilities,
    )
    from hevi.longcat.oprim.context import estimate_tokens, pack_context, rank_context_blocks
    from hevi.longcat.oprim.contracts import LongCatContextBlock, LongCatRequest, LongCatTool
    from hevi.longcat.oprim.protocol import ModelTurn, normalize_model_turn
    from hevi.longcat.oservi.provider import build_longcat_caller, longcat_provider_status
    from hevi.longcat.oskill.agent import execute_agent_loop
    from hevi.longcat.oskill.compiler import compile_longcat_request

    blocks = (
        LongCatContextBlock("high", "history war decision", priority=1, recency=1),
        LongCatContextBlock("long", "x" * 300, priority=0),
        LongCatContextBlock("empty", ""),
    )
    assert estimate_tokens("") == 0 and estimate_tokens("历史") >= 1
    assert rank_context_blocks("history", blocks)[0][0].block_id == "high"
    packed = pack_context("history", blocks, max_tokens=20)
    assert packed.blocks and packed.as_message() and packed.to_dict()["fingerprint"]
    with pytest.raises(ValueError):
        pack_context("x", blocks, max_tokens=0)

    tool = LongCatTool("lookup", "look up", {"type": "object"})
    request = LongCatRequest(
        goal="history", context_blocks=blocks[:2], tools=(tool,), max_context_tokens=1024
    )
    compiled = compile_longcat_request(request)
    assert compiled["status"] == "ready" and compiled["payload"]["tools"]
    assert LongCatRequest(goal="", max_context_tokens=1).validate()
    assert tool.to_openai()["function"]["name"] == "lookup"
    raw_turn = normalize_model_turn(
        {
            "choices": [
                {
                    "message": {
                        "content": [{"text": "ok"}],
                        "tool_calls": [
                            {"id": "1", "function": {"name": "lookup", "arguments": '{"q":"x"}'}}
                        ],
                    }
                }
            ]
        }
    )
    assert (
        raw_turn.content == "ok"
        and not raw_turn.is_final
        and raw_turn.tool_calls[0].arguments["q"] == "x"
    )
    assert normalize_model_turn(None).content == ""
    assert ModelTurn(content="done").is_final

    calls = 0

    async def caller(**_payload: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"id": "c1", "function": {"name": "lookup", "arguments": "{}"}}
                            ]
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "completed"}}], "usage": {"prompt_tokens": 10}}

    loop = await execute_agent_loop(
        request, caller, tool_handlers={"lookup": lambda _args: {"status": "ok"}}
    )
    assert loop["status"] == "completed" and len(loop["tool_calls"]) == 1
    blocked = await longcat_agent_workflow({"max_context_tokens": 1}, {"goal": "x"}, tmp_path)
    assert blocked["status"] == "blocked" and (tmp_path / "longcat_report.json").exists()
    configured = await longcat_agent_workflow(
        LongCatConfig(caller=caller), {"goal": "x"}, tmp_path / "configured"
    )
    assert configured["status"] == "completed"
    assert longcat_capabilities()["status"] == "unavailable"
    monkeypatch.delenv("LONGCAT_BASE_URL", raising=False)
    assert build_longcat_caller() is None and longcat_provider_status()["available"] is False


def test_capability_catalog_and_joyai_session_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.joyai.omodul.stream_edit import (
        capabilities,
        create_session,
        finish_session,
        record_frame,
        record_output,
        reset_sessions,
        start_session,
        stream_provider_url,
    )
    from hevi.joyai.oprim.stream_contract import frame_budget, validate_control
    from hevi.production.capabilities import (
        CapabilityUnavailableError,
        capability_catalog,
        require_capability,
        require_production_capability,
    )

    for name in (
        "VOICEBOX_BASE_URL",
        "GEN_ENGINE_BASE_URL",
        "VOICE_ASR_STREAM_WS_URL",
        "JOYAI_STREAM_WS_URL",
        "JOYAI_BASE_URL",
        "PEXELS_API_KEY",
        "DUIX_SERVICE_URL",
        "DUIX_LIVESTREAM_PATH",
        "LONGCAT_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    catalog = {item["id"]: item for item in capability_catalog()}
    assert catalog["longvideo"]["readiness"] == "ready"
    assert catalog["voice_studio_tts"]["readiness"] == "unavailable"
    assert catalog["voice_platform"]["readiness"] == "execution_only"
    assert require_capability("longvideo").id == "longvideo"
    assert require_production_capability("longvideo").id == "longvideo"
    with pytest.raises(CapabilityUnavailableError) as unavailable:
        require_capability("longcat_agent")
    assert unavailable.value.detail()["code"] == "CAPABILITY_UNAVAILABLE"
    with pytest.raises(CapabilityUnavailableError):
        require_production_capability("voice_platform")
    monkeypatch.setenv("JOYAI_BASE_URL", "https://joyai.example")
    monkeypatch.setenv("JOYAI_STREAM_WS_PATH", "/v1/stream")
    assert stream_provider_url() == "wss://joyai.example/v1/stream"
    assert capabilities()["available"] is True
    reset_sessions()
    blocked = create_session(prompt="edit", reference_images=["missing.png"])
    assert blocked.status == "blocked"
    assert start_session(blocked.session_id) is blocked
    running = create_session(prompt="edit")
    assert start_session(running.session_id).status == "running"
    assert record_frame(running.session_id) is running
    assert record_output(running.session_id) is running
    assert running.input_frames == 1 and running.output_frames == 1
    assert finish_session(running.session_id).status == "completed"
    assert finish_session("missing") is None
    assert validate_control({"type": "start", "prompt": "", "width": 1})
    assert validate_control({"type": "frame"})
    assert validate_control({"type": "heartbeat"}) == []
    budget = frame_budget(width=160, height=160, fps=2, seconds=1.5)
    assert budget["frames"] == 3 and budget["raw_bytes"] == 160 * 160 * 4 * 3


@pytest.mark.asyncio
async def test_media_transactions_write_verified_manifests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.production import media_workflows as workflows
    from hevi.production.artifacts import Artifact

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    steps: list[dict[str, object]] = []

    async def burn(video: Path, subtitles: list[Path], output: Path, **_kwargs: object) -> Path:
        assert video == source
        assert all(item.is_file() for item in subtitles)
        output.write_bytes(b"localized-video")
        return output

    monkeypatch.setattr(workflows, "_burn_subtitles", burn)
    localized = await workflows.video_localization_workflow(
        {"target_language": "en", "bilingual": True},
        {
            "source_video_path": str(source),
            "source_segments": [{"start": 0, "end": 1.2, "text": "你好", "speaker": "host"}],
            "translator": lambda _segments, **_kwargs: [{"text": "hello"}],
        },
        tmp_path / "localized",
        on_step=lambda event: steps.append(event),
    )
    assert localized["status"] == "succeeded"
    assert Path(localized["findings"]["output_video_path"]).is_file()
    assert localized["artifacts"] and localized["decision_trail"]
    assert steps[-1]["stage"] == "completed"
    assert workflows.compute_fingerprint_for(
        {"api_key": "secret", "target_language": "en"},
        {"source_segments": [{"text": "private"}]},
    ) == workflows.compute_fingerprint_for(
        {"api_key": "other", "target_language": "en"},
        {"source_segments": [{"text": "different"}]},
    )
    failed = await workflows.video_localization_workflow(
        {}, {"source_video_path": str(tmp_path / "missing.mp4")}, tmp_path / "failed"
    )
    assert failed["status"] == "failed" and failed["artifacts"] == []

    clip = tmp_path / "clip.mp4"

    def renderer(_source: str, *, output_dir: Path, **_kwargs: object) -> dict[str, object]:
        output_dir.mkdir(parents=True, exist_ok=True)
        clip_path = output_dir / clip.name
        clip_path.write_bytes(b"clip-video")
        manifest = {
            "artifacts": [Artifact.from_path(clip_path, kind="video", primary=True).model_dump()]
        }
        return {
            "status": "completed",
            "clips": [{"path": str(clip_path), "start": 0, "end": 1}],
            "result_video_path": str(clip_path),
            "quality": {"passed": True},
            "config_json": {"artifact_manifest": manifest},
        }

    monkeypatch.setattr(workflows, "render_clip_batch", renderer)
    shorts = await workflows.shorts_generation_workflow(
        {"target_clips": 1}, {"source_video_path": str(source)}, tmp_path / "shorts"
    )
    assert shorts["status"] == "succeeded" and shorts["artifacts"]
    task = await workflows.execute_clip_video_task(
        {
            "id": "task-1",
            "config_json": {
                "clip_request": {"video_path": str(source), "target_clips": 1},
                "output_dir": str(tmp_path / "task"),
            },
        },
        None,
    )
    assert task["status"] == "completed"


def test_speech_catalog_and_asr_quality_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.audio import speech_platform
    from hevi.voicepro_asr.oprim import normalize_audio, verify_asr_result
    from hevi.voicepro_asr.schemas import ASRResult, SentenceSegment, WordTimestamp

    monkeypatch.delenv("VOICEBOX_BASE_URL", raising=False)
    monkeypatch.delenv("GEN_ENGINE_BASE_URL", raising=False)
    engines = speech_platform.list_engines()
    assert {item.id for item in engines} >= {"pocket_tts", "voxcpm", "faster_whisper"}
    assert speech_platform.get_engine("missing") is None
    assert speech_platform.list_voice_profiles()
    unavailable = speech_platform.build_batch_plan(
        [
            {"text": ""},
            {"text": "hello", "engine": "missing"},
            {"text": "hello", "engine": "voxcpm"},
        ]
    )
    assert unavailable["valid"] is False and len(unavailable["errors"]) == 2
    assert unavailable["jobs"][-1]["engine"] == "voxcpm"
    diagnostics = speech_platform.diagnostics()
    assert diagnostics["local_first"] is True and diagnostics["ffmpeg"]

    result = ASRResult(
        text="hello",
        words=[WordTimestamp(word="hello", start_s=0, end_s=1)],
        segments=[SentenceSegment(start_s=0, end_s=1, text="hello", is_complete=True)],
        cer=0,
    )
    assert verify_asr_result(result, expected_text="hello")["passed"] is True
    assert verify_asr_result(result, expected_text="hullo", max_cer=0.01)["passed"] is False
    assert verify_asr_result(ASRResult(text=""), expected_text=None)["passed"] is False
    with pytest.raises(RuntimeError, match="Aliyun"):
        import asyncio

        from hevi.voicepro_asr.oprim import transcribe_aliyun_asr

        asyncio.run(transcribe_aliyun_asr("missing.wav", None))

    calls: list[list[str]] = []

    def ffmpeg(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("hevi.voicepro_asr.oprim.subprocess.run", ffmpeg)
    assert normalize_audio("in.wav", str(tmp_path / "out.wav")) == str(tmp_path / "out.wav")
    assert calls and "pcm_s16le" in calls[0]


def test_tts_contracts_fail_closed_and_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.voicepro_tts import oprim as tts
    from hevi.voicepro_tts.schemas import TTSProvider, make_tts_config

    output = tmp_path / "audio.wav"
    tts._write_nonempty_audio(output, b"wav", "test")
    assert output.read_bytes() == b"wav"
    with pytest.raises(RuntimeError, match="empty audio"):
        tts._write_nonempty_audio(tmp_path / "empty.wav", b"", "test")
    with pytest.raises(RuntimeError, match="non-empty"):
        tts._require_nonempty_audio(tmp_path / "missing.wav", "test")
    with pytest.raises(RuntimeError, match="MiniMax"):
        import asyncio

        asyncio.run(tts.synthesize_minimax_tts("hi", output_path=str(tmp_path / "m.mp3")))
    with pytest.raises(RuntimeError, match="Azure"):
        import asyncio

        asyncio.run(tts.synthesize_azure_tts("hi", output_path=str(tmp_path / "a.wav")))
    assert make_tts_config("edge_tts").provider is TTSProvider.EDGE_TTS

    async def fake_edge(*_args: object, **_kwargs: object) -> object:
        return "edge"

    monkeypatch.setattr(tts, "synthesize_edge_tts", fake_edge)
    import asyncio

    assert await_in_test(tts.synthesize_tts("hi", make_tts_config(TTSProvider.EDGE_TTS))) == "edge"


def await_in_test(awaitable: Any) -> Any:
    """Run a small async adapter from a synchronous contract test."""
    return asyncio.run(awaitable)


def test_digital_human_atoms_keep_artifact_and_qa_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.digital_human.oprim import (
        add_clip_to_timeline,
        build_caption_plan,
        build_timeline,
        generate_narration,
        lock_content,
        run_preflight_check,
        run_qa_gate,
    )
    from hevi.digital_human.oprim.render import (
        _parse_tile,
        _replace_nonempty,
        _run_ffmpeg,
        build_loudnorm_filter,
        calculate_contact_timestamps,
        delivery_report,
        encode_video,
        generate_contact_sheet,
        loudnorm_two_pass,
    )
    from hevi.digital_human.schemas import AudioMeasurement, PresenterJob

    job = PresenterJob(topic="如何识别新闻", duration_target_s=30)
    monkeypatch.setenv("HEVI_DIGITAL_HUMAN_OUTPUT_DIR", str(tmp_path / "dh"))

    def render_voice(_text: str, output: Path, **_kwargs: object) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"real-test-wav")

    monkeypatch.setattr("hevi.voicepro.oskill.synthesize_native_voice_sync", render_voice)
    lock_content(job)
    locked = generate_narration(job)
    assert locked.final_audio and Path(locked.final_audio).is_file()
    timeline = build_timeline(locked, narration_duration_s=30)
    assert timeline.total_video_duration_s == 30
    assert add_clip_to_timeline(timeline, 0, 1, 0, 1, "shot.mp4").clips
    with pytest.raises(ValueError):
        add_clip_to_timeline(timeline, -1, 0, 0, 0, "bad.mp4")
    captions = build_caption_plan(3, "第一句。第二句。", keyword_anchors=[(0.1, "第一")])
    assert captions.phrases and captions.phrases[0].style
    assert run_preflight_check(job).ok is False
    job.rights_confirmed = True
    job.adult_presenter_confirmed = True
    job.remote_upload_approved = True
    job.voice_clone_approved = True
    image = tmp_path / "presenter.png"
    image.write_bytes(b"image")
    job.presenter_image = str(image)
    monkeypatch.setattr(
        "hevi.digital_human.oprim.qa._ffprobe",
        lambda _path: {"width": 1024, "height": 1024, "streams": [{"codec_type": "video"}]},
    )
    preflight = run_preflight_check(job)
    assert preflight.remote_ready is True
    qa = run_qa_gate(job, mouth_sync=False)
    assert qa.ok is False and "mouth_sync" in qa.errors[0]
    job.rendered = locked.final_audio
    assert run_qa_gate(job).ok is True

    measurement = AudioMeasurement(
        input_i=-16,
        input_tp=-1,
        input_lra=4,
        input_thresh=-26,
        target_offset=0,
        measured_lufs=-16,
        program_lufs=-16,
    )
    assert "measured_I=-16" in build_loudnorm_filter(measurement)
    assert calculate_contact_timestamps(0, 3) == [0.2, 0.2, 0.2]
    assert len(calculate_contact_timestamps(10, 4)) == 4
    assert _parse_tile("3x2") == (3, 2)
    with pytest.raises(ValueError):
        _parse_tile("bad")
    with pytest.raises(FileNotFoundError):
        encode_video(str(tmp_path / "missing.mp4"), str(tmp_path / "out.mp4"))

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    temporary = tmp_path / "temporary.bin"
    temporary.write_bytes(b"x")
    replaced = tmp_path / "replaced.bin"
    _replace_nonempty(temporary, replaced, "test")
    assert replaced.read_bytes() == b"x"
    with pytest.raises(RuntimeError):
        _run_ffmpeg(["ffmpeg"], "test")

    def run_media(command: list[str], _operation: str) -> None:
        Path(command[-1]).write_bytes(b"encoded")

    monkeypatch.setattr("hevi.digital_human.oprim.render._run_ffmpeg", run_media)
    monkeypatch.setattr("hevi.digital_human.oprim.render._probe_duration", lambda _path: 2.0)
    assert encode_video(str(source), str(tmp_path / "encoded.mp4")) is True
    assert generate_contact_sheet(str(source), str(tmp_path / "sheet.png")) is True
    monkeypatch.setattr(
        "hevi.digital_human.oprim.render._measure_loudnorm",
        lambda *_args: {
            "input_i": -16.0,
            "input_tp": -1.0,
            "input_lra": 4.0,
            "input_thresh": -26.0,
            "target_offset": 0.0,
            "measured_lufs": -16.0,
        },
    )
    normalized = loudnorm_two_pass(str(source), str(tmp_path / "normalized.mp4"))
    assert normalized.program_lufs == -16
    report = delivery_report(
        str(replaced), str(replaced), str(replaced), 1.0, measurement, {}, {}, {}
    )
    assert report["status"] == "verified" and report["full_decode_passed"] is True


def test_media_provider_chain_freezes_local_stock_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.sourcing import media_providers as providers

    local_asset = tmp_path / "local.wav"
    local_asset.write_bytes(b"local")

    class Library:
        def select_bgm(self, _intent: str) -> Path:
            return local_asset

        def get_sfx(self, _token: str) -> Path:
            return local_asset

    monkeypatch.setattr("hevi.audio.bgm_library.BGMLibrary", Library)
    assert providers._bgm_local("calm") == local_asset
    assert providers._sfx_local("hit/swish") == local_asset
    grade = providers._grade_local("warm_film")
    assert grade and grade.is_file() and json.loads(grade.read_text())["name"] == "warm_film"
    monkeypatch.setenv("MATERIAL_CACHE_DIR", str(tmp_path / "cache"))

    class StreamResponse:
        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, _size: int):
            yield b"frozen-asset"

    class StreamContext:
        def __enter__(self) -> StreamResponse:
            return StreamResponse()

        def __exit__(self, *_args: object) -> None:
            return None

    class Client:
        def get(self, _url: str, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {
                    "photos": [
                        {
                            "id": 7,
                            "url": "https://pexels.test/photo",
                            "photographer": "tester",
                            "src": {"large": "https://cdn.test/image.jpg"},
                        }
                    ]
                },
            )

        def stream(self, _method: str, _url: str) -> StreamContext:
            return StreamContext()

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setenv("PEXELS_API_KEY", "present-but-test-injected")
    monkeypatch.setattr(providers.httpx, "Client", lambda **_kwargs: Client())
    image = providers._image_stock("lantern")
    assert image and image.is_file() and image.with_suffix(".jpg.source.json").is_file()
    provenance = json.loads(image.with_suffix(".jpg.source.json").read_text())
    assert provenance["provider"] == "pexels" and provenance["sha256"]
    assert (
        providers._download_cached(
            "https://cdn.test/image.jpg", tmp_path / "cache", ".jpg", Client()
        )
        == image
    )
    assert providers._lut_local("missing") is None

    video = tmp_path / "stock.mp4"
    video.write_bytes(b"video")
    item = SimpleNamespace(
        source="pexels",
        id="video-1",
        page_url="https://pexels.test/video",
        title="demo",
        width=720,
        height=1280,
        duration_s=2.0,
    )
    monkeypatch.setattr("hevi.video.material_corpus.search_all", lambda *_args, **_kwargs: [item])
    monkeypatch.setattr("hevi.video.material_corpus.dedupe", lambda items: items)
    monkeypatch.setattr(
        "hevi.video.material_corpus.rank_by_keywords", lambda items, *_args, **_kwargs: items
    )
    monkeypatch.setattr(
        "hevi.video.material_corpus.ensure_cached",
        lambda *_args, **_kwargs: SimpleNamespace(cached_path=str(video)),
    )
    assert providers._video_stock("portrait 9:16") == video
    chain = providers.default_providers()
    assert set(chain) == {"bgm", "sfx", "voice", "grade", "lut", "image", "video"}


@pytest.mark.asyncio
async def test_openai_audio_facade_and_asr_adapters_return_real_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.ingest.video_transcript import TranscriptSegment, WordSpan
    from hevi.voicepro.omodul import openai_audio

    class Engine:
        kind = "tts"
        available = True
        setup = None
        id = "test_tts"

    monkeypatch.setattr(openai_audio, "get_engine", lambda _engine: Engine())

    async def synthesize(_engine: str, *, output_path: Path, **_kwargs: object) -> None:
        output_path.write_bytes(b"audio")

    monkeypatch.setattr("hevi.audio.task_adapter._synthesize_with_engine", synthesize)
    wav = await openai_audio.synthesize_audio_file(
        text="hello", engine="test_tts", output_dir=tmp_path / "audio"
    )
    assert wav["format"] == "wav" and Path(wav["path"]).is_file()

    async def convert(_source: Path, output: Path, _fmt: str) -> None:
        output.write_bytes(b"converted")

    monkeypatch.setattr(openai_audio, "_convert_audio", convert)
    mp3 = await openai_audio.synthesize_audio_file(
        text="hello", engine="test_tts", response_format="mp3", output_dir=tmp_path / "audio"
    )
    assert mp3["media_type"] == "audio/mpeg" and Path(mp3["path"]).is_file()
    with pytest.raises(ValueError):
        await openai_audio.synthesize_audio_file(text="", engine="test_tts")
    with pytest.raises(ValueError):
        await openai_audio.synthesize_audio_file(text="x", engine="test_tts", response_format="bad")

    class ASREngine:
        kind = "asr"
        available = True
        setup = None

    monkeypatch.setattr(
        openai_audio,
        "get_engine",
        lambda engine: ASREngine() if engine == "asr" else Engine(),
    )
    segments = [
        TranscriptSegment(
            start=0,
            end=1,
            text="hello",
            words=(WordSpan(word="hello", start=0, end=1),),
        )
    ]
    monkeypatch.setattr(openai_audio, "fetch_transcript", lambda *_args, **_kwargs: segments)
    assert (
        "WEBVTT"
        in openai_audio.transcribe_audio_file(
            source=tmp_path / "source.wav", asr_engine="asr", response_format="vtt"
        )["text"]
    )
    assert (
        openai_audio.transcribe_audio_file(
            source=tmp_path / "source.wav", asr_engine="asr", response_format="text"
        )["format"]
        == "text"
    )


@pytest.mark.asyncio
async def test_stream_edit_routes_expose_provider_unavailable_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from hevi.api.routers import stream_edit as routes
    from hevi.joyai.omodul.stream_edit import reset_sessions

    async def unavailable(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"ready": False, "error": "not configured"}

    monkeypatch.setattr(routes, "probe_provider", unavailable)
    capabilities = await routes.stream_capabilities()
    assert capabilities["available"] is False
    assert capabilities["provider_runtime"]["ready"] is False
    budget = await routes.stream_budget()
    assert budget["frames"] == 24
    with pytest.raises(HTTPException):
        await routes.stream_budget(width=100)
    reset_sessions()
    created = await routes.create_stream_session(routes.StreamEditCreateRequest(prompt="edit"), {})
    assert created["status"] == "blocked"
    assert "unavailable" in created["last_error"].lower()
    listed = await routes.sessions({})
    assert listed["total"] == 1
    current = await routes.stream_session(created["session_id"], {})
    assert current["session_id"] == created["session_id"]
    finished = await routes.finish_stream_session(created["session_id"], {})
    assert finished["status"] == "completed"
    with pytest.raises(HTTPException):
        await routes.stream_session("missing", {})


def test_digital_human_plan_contracts_are_serializable(tmp_path: Path) -> None:
    from hevi.digital_human.omodul import (
        build_full_job_plan,
        init_job,
        plan_composition,
        plan_delivery,
        plan_generation,
        plan_presenter_generation,
        plan_visual,
    )

    image = tmp_path / "presenter.png"
    image.write_bytes(b"image")
    job_dir = tmp_path / "job"
    job = init_job(
        str(job_dir),
        str(image),
        topic="历史讲解",
        rights_confirmed=True,
        adult_presenter_confirmed=True,
        remote_upload_approved=True,
        voice_clone_approved=True,
    )
    assert (job_dir / "job.json").is_file()
    generation = plan_generation(job)
    visual = plan_visual(job, 12.0)
    presenter = plan_presenter_generation(job)
    composition = plan_composition(job)
    delivery = plan_delivery(job, "render.mp4", str(job_dir / "outputs"))
    full = build_full_job_plan(job, 12.0, "render.mp4", str(job_dir / "outputs"))
    assert generation["target_status"] == "audio_locked"
    assert visual["target_status"] == "visual_plan_locked"
    assert presenter["target_status"] == "presenter_generated"
    assert composition["target_status"] == "composition_checked"
    assert delivery["target_status"] == "verified"
    assert len(full["phases"]) == 5 and full["state_machine"][-1] == "verified"


@pytest.mark.asyncio
async def test_montage_stage_contracts_pause_and_resume_without_fake_media(
    tmp_path: Path,
) -> None:
    from hevi.montage.omodul.agentic import (
        AgenticMontageConfig,
        _idea,
        _proposal,
        _rig_plan,
        _scene_plan,
        agentic_montage_workflow,
    )

    assert _proposal({"topic": "城市场景"}, {})["proposal_status"] == "planned"
    assert _idea({}, {})["status"] == "failed"
    scene = _scene_plan({"script_lines": ["开场", {"text": "转折", "duration_s": 2}]}, {})
    assert len(scene["scene_plan"]) == 2
    assert _rig_plan({"character_design": {"subjects": ["hero"]}}, {})["rig_plan"]["subjects"] == [
        "hero"
    ]
    report = await agentic_montage_workflow(
        AgenticMontageConfig(
            pipeline="framework-smoke",
            execute=False,
            auto_approve=True,
        ),
        {
            "topic": "demo",
            "stage_handlers": {
                "research": lambda _data, _context: {"research": {"context": "evidence"}},
                "script": lambda _data, _context: {"script_lines": ["demo"]},
            },
        },
        tmp_path / "montage",
    )
    assert report["status"] == "planned"
    assert (tmp_path / "montage" / "montage_report.json").is_file()
    blocked = await agentic_montage_workflow(
        {"pipeline": "framework-smoke", "estimated_cost_usd": 10, "budget_usd": 1},
        {"topic": "demo"},
        tmp_path / "budget",
    )
    assert blocked["status"] == "blocked" and blocked["stage"] == "preflight"


@pytest.mark.asyncio
async def test_identity_pack_runs_injected_image_voice_and_manifest_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise the identity-pack state machine without calling a cloud provider."""
    import hashlib

    from PIL import Image

    import hevi.vault.identity_pack as identity
    from hevi.vault.schemas import Manifest, ManifestFile

    prompts: list[str] = []
    created_manifest: Manifest | None = None

    async def image_gen(*, prompt: str, output_path: Path, **_kwargs: object) -> Path:
        prompts.append(prompt)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), (40, 80, 120)).save(output_path)
        return output_path

    async def video_gen(*, output_path: Path, **_kwargs: object) -> Path:
        output_path.write_bytes(b"real-turnaround-video")
        return output_path

    async def tts_fn(*, output_path: Path, **_kwargs: object) -> Path:
        output_path.write_bytes(b"real-voice-sample")
        return output_path

    async def create_manifest(_pool: object, _minio: object, **kwargs: object) -> Manifest:
        nonlocal created_manifest
        raw_files = kwargs["files"]
        roles = kwargs["file_roles"]
        assert isinstance(raw_files, dict) and isinstance(roles, dict)
        files = {
            str(name): ManifestFile(
                sha256=hashlib.sha256(bytes(data)).hexdigest(), role=str(roles.get(name, ""))
            )
            for name, data in raw_files.items()
        }
        created_manifest = Manifest(
            pack_id=str(kwargs["pack_id"]),
            pack_type=str(kwargs["pack_type"]),
            version=str(kwargs["version"]),
            name=str(kwargs["name"]),
            files=files,
            immutable_traits=str(kwargs["immutable_traits"]),
            era_lock=str(kwargs["era_lock"]),
            embeddings=dict(kwargs["embeddings"]),
            voice=dict(kwargs["voice"]),
            stability_check=kwargs["stability_check"],
            provenance=kwargs["provenance"],
        )
        return created_manifest

    async def promote(_pool: object, *, stability_check: Any, **_kwargs: object) -> Manifest:
        assert stability_check.passed is True
        assert created_manifest is not None
        return created_manifest.model_copy(update={"lifecycle": "validated"})

    monkeypatch.setattr(identity, "asset_create", create_manifest)
    monkeypatch.setattr(identity, "asset_promote", promote)
    monkeypatch.setattr(identity, "store_embedding", lambda *_args, **_kwargs: asyncio.sleep(0))
    monkeypatch.setattr(identity, "subject_embed", lambda **_kwargs: [1.0, 0.0, 0.0])

    async def vlm(_vlm: object, _prompt: str, _path: Path) -> dict[str, object]:
        return {"passes": True, "violations": []}

    monkeypatch.setattr("hevi.tongjian.character_bible._call_vlm_json", vlm)
    result = await identity.build_identity_pack(
        pool=object(),
        minio_client=object(),
        character_id="hero",
        name="Hero",
        appearance="black robe",
        era_lock="ancient",
        art_direction="realistic",
        output_dir=tmp_path / "identity",
        expressions={"neutral": "calm", "angry": "angry"},
        image_gen=image_gen,
        vlm=object(),
        video_gen=video_gen,
        tts_fn=tts_fn,
        build_turnaround_video=True,
        run_id="run-1",
        image_appearance="a historical actor",
        image_era_lock="period costume",
    )
    assert result.lifecycle == "validated"
    assert result.stability_check.score == "3/3"
    assert result.files["refs/front.png"].role == "canonical_portrait"
    assert result.files["refs/grid9.png"].role == "multiview_grid"
    assert result.files["refs/action_pose.png"].role == "action_pose"
    assert result.voice["tts_voice_id"] == "cosyvoice:hero_cloned"
    assert len(prompts) == 3 + 9 + 1 + 2
    assert (tmp_path / "identity" / "grid9.png").is_file()


@pytest.mark.asyncio
async def test_asr_success_adapters_and_tts_dispatch_cover_real_shapes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys
    from types import ModuleType, SimpleNamespace

    from hevi.voicepro_asr.oprim import (
        transcribe_faster_whisper,
        transcribe_openai_whisper,
        transcribe_whisper_cpp,
    )
    from hevi.voicepro_asr.schemas import make_asr_config
    from hevi.voicepro_tts import oprim as tts
    from hevi.voicepro_tts.schemas import TTSProvider, make_tts_config

    fw = ModuleType("faster_whisper")

    class FakeWhisperModel:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def transcribe(self, *_args: object, **_kwargs: object):
            word = SimpleNamespace(word="hello", start=0.0, end=0.5)
            segment = SimpleNamespace(text=" hello ", start=0.0, end=1.0, words=[word])
            return [segment], SimpleNamespace(language="en", duration=1.0)

    fw.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    faster = await transcribe_faster_whisper(
        "input.wav", make_asr_config("faster_whisper", model="tiny", language="en")
    )
    assert faster.text == "hello" and faster.words[0].start_ms == 0

    source = tmp_path / "input.wav"
    source.write_bytes(b"wav")

    def run_cpp(command: list[str], **_kwargs: object) -> SimpleNamespace:
        output_base = Path(command[command.index("-of") + 1])
        output_base.with_suffix(".json").write_text(
            '{"transcription":[{"text":"hello","offsets":{"from":0,"to":1000}}]}'
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("WHISPER_CPP_BIN", "/bin/whisper-cli")
    monkeypatch.setenv("WHISPER_CPP_MODEL", "/models/tiny.bin")
    monkeypatch.setattr("hevi.voicepro_asr.oprim.subprocess.run", run_cpp)
    cpp = await transcribe_whisper_cpp(str(source), make_asr_config("whisper_cpp"))
    assert cpp.text == "hello" and cpp.duration_s == 1.0

    class OpenAIResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "text": "hello",
                "language": "en",
                "duration": 1.2,
                "segments": [{"text": "hello", "start": 0, "end": 1.2}],
                "words": [{"word": "hello", "start": 0, "end": 1.0}],
            }

    class OpenAIClient:
        async def __aenter__(self) -> OpenAIClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> OpenAIResponse:
            return OpenAIResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: OpenAIClient())
    openai_result = await transcribe_openai_whisper(
        str(source), make_asr_config("openai_whisper", model="whisper-1", language="en")
    )
    assert openai_result.words[0].end_ms == 1000 and openai_result.duration_s == 1.2

    async def fake_tts(*_args: object, **_kwargs: object) -> str:
        return "ok"

    for provider, name in (
        (TTSProvider.EDGE_TTS, "synthesize_edge_tts"),
        (TTSProvider.OPEN_AI_TTS, "synthesize_openai_tts"),
        (TTSProvider.MINIMAX_TTS, "synthesize_minimax_tts"),
        (TTSProvider.COSYVOICE_TTS, "synthesize_cosyvoice"),
        (TTSProvider.F5_TTS, "synthesize_f5_tts"),
        (TTSProvider.KOKORO_TTS, "synthesize_kokoro_tts"),
        (TTSProvider.AZURE_TTS, "synthesize_azure_tts"),
    ):
        monkeypatch.setattr(tts, name, fake_tts)
        assert await tts.synthesize_tts("hello", make_tts_config(provider)) == "ok"
    with pytest.raises(ValueError, match="不支持"):
        await tts.synthesize_tts("hello", SimpleNamespace(provider="unknown"))


@pytest.mark.asyncio
async def test_tongjian_review_api_and_download_paths_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fastapi import BackgroundTasks, HTTPException

    from hevi.api.routers import tongjian
    from hevi.tongjian.schemas import Constitution, Script, ScriptLine

    user = {"id": "review-user"}
    tongjian._EXECUTION_CONTEXTS.clear()
    body = tongjian.RunRequest(source_name="史料", raw_text="原文", pause_after="L2")
    started = await tongjian.start_run(body, BackgroundTasks(), user, None)
    assert started["status"] == "PENDING"
    run_id = started["run_id"]
    record = tongjian._context(run_id)
    record.update(
        {
            "user_id": user["id"],
            "run_dir": str(tmp_path / "run"),
            "status": "AWAITING_REVIEW",
            "constitution": Constitution(thesis="thesis"),
            "script": Script(lines=[ScriptLine(line_id="old", text="旧")]),
        }
    )
    assert (await tongjian.list_runs(user, None))[0].run_id == run_id
    assert (await tongjian.get_run(run_id, user, None)).status == "AWAITING_REVIEW"
    review = await tongjian.get_run_script(run_id, user, None)
    assert review["script"]["lines"][0]["text"] == "旧"
    updated = await tongjian.update_run_script(
        run_id,
        tongjian.ScriptReviewUpdate(
            script=Script(lines=[ScriptLine(line_id="x", text="新")]),
            constitution=Constitution(thesis="edited"),
        ),
        user,
        None,
    )
    assert updated["lines"] == "1"
    assert tongjian._context(run_id)["script"].lines[0].line_id == "LN001"
    resume = await tongjian.resume_run(run_id, BackgroundTasks(), user, None)
    assert resume["status"] == "RUNNING"
    tongjian._context(run_id)["status"] = "AWAITING_REVIEW"
    regenerate = await tongjian.regenerate_script(run_id, BackgroundTasks(), user, None)
    assert regenerate["status"] == "RUNNING"

    with pytest.raises(HTTPException) as missing:
        await tongjian.get_run("missing", user, None)
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as no_token:
        await tongjian.download_run_video(run_id)
    assert no_token.value.status_code == 401
    with pytest.raises(HTTPException) as bad_id:
        await tongjian.download_run_video("not-a-uuid", token="token")
    assert bad_id.value.status_code == 401

    output = tmp_path / "output" / "tongjian" / run_id / "L8"
    output.mkdir(parents=True)
    (output / "final.mp4").write_bytes(b"real-video")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tongjian, "decode_access_token", lambda _token: {"sub": user["id"]})
    response = await tongjian.download_run_video(run_id, token="valid")
    assert response.media_type == "video/mp4"
    assert str(response.path).endswith("final.mp4")


@pytest.mark.asyncio
async def test_director_release_contracts_cover_local_state_and_stage_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise the director state machine's non-provider release branches."""
    from dataclasses import dataclass
    from types import SimpleNamespace

    from fastapi import BackgroundTasks, HTTPException

    import hevi.api.routers.director_pipeline as director
    from hevi.director.pipeline_schemas import (
        Concept,
        DesignCharacter,
        DesignList,
        DesignScene,
        SceneStageSet,
        Screenplay,
        ScreenplayScene,
        ShotList,
        ShotListItem,
    )

    def concept() -> Concept:
        return Concept(theme="冲突", tone="克制", duration_archetype="short")

    def screenplay() -> Screenplay:
        return Screenplay(
            scenes=[
                ScreenplayScene(
                    scene_no=1,
                    location="庭院",
                    characters_present=["甲"],
                    narration="甲走入庭院。",
                    visual_actions=["走入"],
                )
            ]
        )

    def design_list() -> DesignList:
        return DesignList(
            characters=[DesignCharacter(name="甲", appearance="黑衣")],
            scenes=[DesignScene(name="庭院", environment="夜")],
        )

    def shot_list() -> ShotList:
        return ShotList(
            shots=[
                ShotListItem(
                    shot_id="S001",
                    scene_no=1,
                    scene_name="庭院",
                    visual_prompt="甲走入庭院",
                    character_names=["甲"],
                )
            ]
        )

    user = {"id": "coverage-director-user"}
    director._LOCAL_WORK_PROJECTIONS.clear()
    work_id = "coverage-director-work"
    record = director._init_work(
        work_id,
        material_text="史料中的一场冲突",
        intent_hint="",
        user_id=user["id"],
        cache=False,
    )
    director._LOCAL_WORK_PROJECTIONS[work_id] = record
    assert director._require_work(work_id, user) is record
    with pytest.raises(HTTPException):
        director._require_work(work_id, {"id": "other"})
    with pytest.raises(HTTPException):
        director._require_work("missing", user)
    with pytest.raises(HTTPException):
        director._require_stage_ready(record, "screenplay")
    record["locked_through"] = 4
    record.update(
        {
            "concept": {"theme": "x"},
            "screenplay": {"scenes": []},
            "design_list": {},
            "scene_stage": {},
            "shot_list": {},
            "constraint_graph": {"stale": True},
            "video_task_id": "old-task",
        }
    )
    director._rollback_downstream(record, "scene_stage")
    assert record["locked_through"] == 2 and record["scene_stage"] is None
    assert record["shot_list"] is None and "constraint_graph" not in record
    director._append_trail(record, "coverage", "succeeded", "state checked")
    assert director._work_status(record)["decision_trail"][-1]["stage"] == "coverage"

    @dataclass
    class Finding:
        code: str

    monkeypatch.setattr(director, "lint_scene_stage", lambda *_args: [Finding("scene")])
    monkeypatch.setattr(director, "lint_h3_cut_budget", lambda *_args: [Finding("cut")])
    monkeypatch.setattr(director, "lint_h3_vocab", lambda *_args: [Finding("vocab")])
    monkeypatch.setattr(director, "lint_shuohao_storyboard", lambda *_args: [Finding("story")])
    monkeypatch.setattr(director, "append_gate_log", lambda *_args: None)
    monkeypatch.setattr(director, "gate_log_entries", lambda **_kwargs: [])
    director._record_shot_lints(record, ShotList(), SceneStageSet())
    assert {item["code"] for item in record["scene_stage_lint"]} == {
        "scene",
        "cut",
        "vocab",
        "story",
    }

    failed_gate = director._build_director_gate(
        story=SimpleNamespace(characters=[], events=[]),
        season_plan=SimpleNamespace(episodes=[], target_episodes=1),
        plan_gate=SimpleNamespace(
            passed=False, coverage=0.0, errors=["no plan"], warnings=["warn"]
        ),
        screenplay=Screenplay(),
        design_list=DesignList(),
        estimated_cost_usd=20.0,
        season_budget_usd=1.0,
    )
    assert failed_gate.passed is False and failed_gate.errors and failed_gate.warnings == ["warn"]

    async def fake_estimate(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(total_usd=2.5)

    monkeypatch.setattr("hevi.cost.estimator.estimate_cost", fake_estimate)
    assert (
        await director._estimate_season_cost(
            duration_archetype="short",
            video_provider="local",
            audio_provider="edge_tts",
            character_count=0,
            episode_count=2,
        )
        == 5.0
    )

    body = director.ParseWorkRequest(
        work_name="解析测试", material_text="一段素材", target_episodes=1
    )
    accepted = await director.parse_work(body, BackgroundTasks(), user)
    parsed_id = accepted["work_id"]
    assert accepted["status"] == "parsing"
    assert (await director.list_works(user))[0]["work_id"] == parsed_id
    assert (await director.get_work(parsed_id, user))["status"] == "parsing"
    with pytest.raises(HTTPException):
        await director.parse_work(
            director.ParseWorkRequest(work_name="x", material_text="x", episode_duration="bad"),
            BackgroundTasks(),
            user,
        )
    with pytest.raises(HTTPException):
        await director.parse_work(
            director.ParseWorkRequest(work_name="x", material_text="   "),
            BackgroundTasks(),
            user,
        )

    record["design_list"] = design_list().model_dump()
    record["shot_list"] = shot_list().model_dump()
    await director._persist_work(record)
    constraints = await director.get_work_constraints(work_id, user)
    assert constraints["source"] == "compatibility_projection" and constraints["graph"]
    compiled = await director.compile_work_constraints(
        work_id,
        director.CompileConstraintsRequest(provider_id="local", supported_constraints=set()),
        user,
    )
    assert compiled["coverage"]["unsupported_constraints"]
    with pytest.raises(HTTPException):
        await director.compile_work_constraints(
            parsed_id,
            director.CompileConstraintsRequest(provider_id="local"),
            user,
        )

    monkeypatch.setattr(director, "_resolve_llm", lambda: object())
    monkeypatch.setattr(
        director,
        "generate_screenplay_draft",
        lambda **_kwargs: asyncio.sleep(0, result=screenplay()),
    )
    record["concept"] = concept().model_dump()
    await director._run_screenplay_generate(work_id)
    assert record["status"] == "screenplay_draft"
    monkeypatch.setattr(
        director,
        "generate_screenplay_draft",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("screenplay broken")),
    )
    await director._run_screenplay_generate(work_id)
    assert record["status"] == "screenplay_generate_failed"

    record["screenplay"] = screenplay().model_dump()
    record["design_list"] = design_list().model_dump()
    monkeypatch.setattr(
        director,
        "_build_scene_stage_set",
        lambda *_args: asyncio.sleep(0, result=SceneStageSet()),
    )
    await director._run_scene_stage_regenerate(work_id)
    assert record["status"] == "scene_stage_draft"
    monkeypatch.setattr(
        director,
        "_build_scene_stage_set",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("scene stage broken")),
    )
    await director._run_scene_stage_regenerate(work_id)
    assert record["status"] == "scene_stage_regenerate_failed"

    async def fake_shots(**_kwargs: object) -> ShotList:
        return shot_list()

    monkeypatch.setattr(director, "generate_shot_list_draft", fake_shots)
    monkeypatch.setattr(director, "_attach_kernel_plan", lambda _shots: {})
    monkeypatch.setattr(director, "_record_shot_lints", lambda *_args: None)
    record["scene_stage"] = None
    await director._run_shot_list_regenerate(work_id)
    assert record["status"] == "shot_list_draft"
    monkeypatch.setattr(
        director,
        "generate_shot_list_draft",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("shot list broken")),
    )
    await director._run_shot_list_regenerate(work_id)
    assert record["status"] == "shot_list_regenerate_failed"

    locked = design_list()
    monkeypatch.setattr(
        director,
        "_lock_design_list_assets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("asset lock broken")),
    )
    record["screenplay"] = screenplay().model_dump()
    await director._run_design_list_lock(
        work_id,
        locked,
        user_id=user["id"],
        subject_svc=SimpleNamespace(),
    )
    assert record["status"] == "design_list_lock_failed"

    assert director._derive_shot_id(None) == ""
    assert director._derive_shot_id("shot.mp4") == "shot"
    assert director._derive_shot_id("SH001_01_talk.mp4") == "SH001_01"
    for name in ("clip", "talk", "vis", "narr", "kf", "first"):
        (tmp_path / f"SH001_01_{name}.mp4").write_bytes(b"x")
    director._purge_shot_artifacts(tmp_path, "SH001_01", hard=False)
    assert (tmp_path / "SH001_01_kf.mp4").exists()
    director._purge_shot_artifacts(tmp_path, "SH001_01", hard=True)
    assert not (tmp_path / "SH001_01_kf.mp4").exists()
    director._purge_shot_artifacts(tmp_path, "", hard=True)


@pytest.mark.asyncio
async def test_tongjian_runtime_layers_and_resume_boundaries_are_exercised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cover resumable Tongjian control flow with deterministic local adapters."""
    from types import SimpleNamespace

    from fastapi import BackgroundTasks, HTTPException

    import hevi.api.routers.tongjian as tongjian
    import hevi.studio.kit as studio_kit
    import hevi.studio.mix as studio_mix
    import hevi.tongjian.assemble as assemble
    import hevi.tongjian.chapter_ir as chapter_ir_module
    import hevi.tongjian.character_bible as character_bible
    import hevi.tongjian.character_sim as character_sim
    import hevi.tongjian.hotwords as hotwords
    import hevi.tongjian.music_plan as music_plan
    import hevi.tongjian.scene_render as scene_render
    import hevi.tongjian.scene_render_avatar as scene_render_avatar
    import hevi.tongjian.script as script_module
    import hevi.tongjian.shotlist as shotlist_module
    import hevi.tongjian.voiceover as voiceover
    from hevi.tongjian.schemas import (
        ChapterIR,
        ChapterMeta,
        Constitution,
        EventIR,
        GateResult,
        LayerConfig,
        Script,
        ScriptLine,
    )

    chapter = ChapterIR(
        meta=ChapterMeta(source="史料", char_count=4),
        events=[EventIR(event_id="E001", summary="两军相遇")],
    )
    constitution = Constitution(thesis="守住城门")
    script = Script(lines=[ScriptLine(line_id="L1", text="守住城门", event_id="E001")])
    gate = GateResult(passed=True, coverage=1.0)
    user = {"id": "tongjian-coverage-user"}

    def helpers(run_id: str, _req: tongjian.RunRequest):
        def gate_done(layer: str, value: GateResult) -> None:
            tongjian._update_layer(
                run_id,
                layer,
                status="PASSED" if value.passed else "DEGRADED",
                degraded=not value.passed,
                gate_report=value.model_dump(),
                finished_at=tongjian.datetime.now(tongjian.UTC),
            )

        return (lambda _layer: object(), lambda _layer: None, lambda _layer: {}, gate_done)

    real_helpers = tongjian._pipeline_helpers
    monkeypatch.setattr(tongjian, "_pipeline_helpers", helpers)
    monkeypatch.setattr(character_sim, "load_character_states", lambda _path: None)
    monkeypatch.setattr(
        character_sim,
        "simulate_character_states",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={"甲": {"knowledge": []}}),
    )
    monkeypatch.setattr(character_sim, "dump_character_states", lambda *_args: None)
    monkeypatch.setattr(
        character_sim,
        "gate_character_states",
        lambda *_args: SimpleNamespace(passed=True, errors=[]),
    )
    monkeypatch.setattr(
        studio_mix,
        "plan_history_mix",
        lambda _script: asyncio.sleep(
            0,
            result=SimpleNamespace(
                drama_lines=[{"line_id": "L1", "text": "守住城门"}],
                provenance={"passed": True},
                to_dict=lambda: {"commentary_count": 0, "drama_count": 1},
            ),
        ),
    )
    monkeypatch.setattr(studio_kit, "shot_export", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chapter_ir_module,
        "extract_chapter_ir",
        lambda **_kwargs: asyncio.sleep(0, result=chapter),
    )
    monkeypatch.setattr(
        "hevi.tongjian.constitution.build_constitution",
        lambda *_args, **_kwargs: asyncio.sleep(0, result=(constitution, gate)),
    )
    monkeypatch.setattr(
        script_module,
        "build_script",
        lambda **_kwargs: asyncio.sleep(0, result=(script, gate)),
    )
    real_run_render = tongjian._run_render
    monkeypatch.setattr(tongjian, "_run_render", lambda _run_id: asyncio.sleep(0))

    run_id = "tongjian-pipeline-success"
    tongjian._init_run(run_id, "史料")
    req = tongjian.RunRequest(
        source_name="史料",
        raw_text="甲守城门",
        pause_after="L2",
        reference_url="https://example.test/reference.mp4",
        layer_config={"L6": LayerConfig(model="cloud_avatar")},
    )
    monkeypatch.setattr(
        studio_kit,
        "watch_video_tool",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={"status": "succeeded"}),
    )
    await tongjian._run_pipeline(run_id, req)
    assert tongjian._context(run_id)["status"] == "AWAITING_REVIEW"
    assert (Path("output/tongjian") / run_id / "L2" / "review.json").is_file()

    run_id_no_pause = "tongjian-pipeline-render"
    tongjian._init_run(run_id_no_pause, "史料")
    render_called: list[str] = []

    async def fake_render(run: str) -> None:
        render_called.append(run)

    monkeypatch.setattr(tongjian, "_run_render", fake_render)
    await tongjian._run_pipeline(
        run_id_no_pause,
        req.model_copy(update={"pause_after": None, "reference_url": ""}),
    )
    assert render_called == [run_id_no_pause]
    monkeypatch.setattr(tongjian, "_run_render", real_run_render)

    run_id_l0 = "tongjian-pipeline-l0-fail"
    tongjian._init_run(run_id_l0, "史料")
    monkeypatch.setattr(
        chapter_ir_module,
        "extract_chapter_ir",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("l0 down")),
    )
    await tongjian._run_pipeline(run_id_l0, req)
    assert tongjian._context(run_id_l0)["status"] == "FAILED"

    run_id_l1 = "tongjian-pipeline-l1-fail"
    tongjian._init_run(run_id_l1, "史料")
    monkeypatch.setattr(
        chapter_ir_module,
        "extract_chapter_ir",
        lambda **_kwargs: asyncio.sleep(0, result=chapter),
    )
    monkeypatch.setattr(
        "hevi.tongjian.constitution.build_constitution",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("l1 down")),
    )
    await tongjian._run_pipeline(run_id_l1, req)
    assert tongjian._context(run_id_l1)["status"] == "FAILED"

    run_id_l2 = "tongjian-pipeline-l2-fail"
    tongjian._init_run(run_id_l2, "史料")
    monkeypatch.setattr(
        "hevi.tongjian.constitution.build_constitution",
        lambda **_kwargs: asyncio.sleep(0, result=(constitution, gate)),
    )
    monkeypatch.setattr(
        script_module,
        "build_script",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("l2 down")),
    )
    await tongjian._run_pipeline(run_id_l2, req)
    assert tongjian._context(run_id_l2)["status"] == "FAILED"

    provider_calls: list[tuple[str, str]] = []

    class ProviderRegistry:
        @classmethod
        def get(cls) -> ProviderRegistry:
            return cls()

        def llm(self, name: str) -> object:
            provider_calls.append(("llm", name))
            return object()

        def generic(self, kind: str, name: str) -> object:
            provider_calls.append((kind, name))
            return object()

    monkeypatch.setattr("obase.provider_registry.ProviderRegistry.get", lambda: ProviderRegistry())
    req_with_layers = tongjian.RunRequest(
        source_name="史料",
        raw_text="原文",
        layer_config={"L0": LayerConfig(model="qwen"), "L3": LayerConfig(model="edge")},
    )
    run_id_helpers = "tongjian-helpers"
    tongjian._init_run(run_id_helpers, "史料")
    monkeypatch.setattr(tongjian, "_pipeline_helpers", real_helpers)
    llm, tts, params, gate_done = tongjian._pipeline_helpers(run_id_helpers, req_with_layers)
    assert llm("L0") and tts("L3") and params("L0") == {}
    gate_done("L1", gate)
    assert tongjian._context(run_id_helpers)["layers"]["L1"]["status"] == "PASSED"
    assert provider_calls == [("llm", "qwen"), ("audio", "edge")]
    cloud_req = req_with_layers.model_copy(
        update={
            "layer_config": {
                "L6": LayerConfig(model="cloud_avatar"),
                "L1": LayerConfig(params={"n": 2}),
            }
        }
    )
    tongjian._apply_cloud_avatar_preset(cloud_req)
    assert cloud_req.layer_config["L0"].model == "qwen_cloud"
    assert req_with_layers.layer_config["L0"].model == "qwen"

    record = tongjian._context(run_id_helpers)
    record["req"] = req_with_layers.model_dump()
    assert tongjian._request_from_record(record).source_name == "史料"
    with pytest.raises(RuntimeError):
        tongjian._request_from_record({})
    with pytest.raises(RuntimeError):
        tongjian._context("missing")
    await tongjian._flush_run_persistence(run_id_helpers)

    monkeypatch.setattr(
        hotwords,
        "build_asr_hotwords",
        lambda _chapter: ["守城"],
    )
    monkeypatch.setattr(tongjian, "_pipeline_helpers", helpers)
    monkeypatch.setattr(
        voiceover,
        "build_voiceover",
        lambda **_kwargs: asyncio.sleep(0, result=(SimpleNamespace(), gate)),
    )
    monkeypatch.setattr(
        character_bible,
        "generate_character_bible",
        lambda **_kwargs: asyncio.sleep(0, result={"甲": "守将"}),
    )
    monkeypatch.setattr(
        shotlist_module,
        "build_shotlist",
        lambda **_kwargs: asyncio.sleep(0, result=([], gate)),
    )
    monkeypatch.setattr(scene_render, "render_shots", lambda **_kwargs: asyncio.sleep(0, result={}))
    monkeypatch.setattr(scene_render, "gate_frame_manifest", lambda *_args: gate)
    monkeypatch.setattr(scene_render_avatar, "gate_avatar_manifest", lambda *_args: gate)
    monkeypatch.setattr(
        music_plan,
        "build_music_plan",
        lambda **_kwargs: asyncio.sleep(0, result=(None, gate)),
    )
    final_path = tmp_path / "final.mp4"
    final_path.write_bytes(b"video")
    monkeypatch.setattr(
        assemble,
        "build_final_video",
        lambda **_kwargs: asyncio.sleep(0, result=(SimpleNamespace(video_path=final_path), gate)),
    )
    render_id = "tongjian-render-layers"
    render_record = tongjian._init_run(render_id, "史料")
    render_record.update(
        {
            "req": req,
            "request": req,
            "chapter_ir": chapter,
            "constitution": constitution,
            "script": script,
            "run_dir": str(tmp_path / "render"),
        }
    )
    result = await tongjian._run_render_layers(render_id)
    assert result, (
        tongjian._context(render_id)["status"],
        tongjian._context(render_id).get("error"),
    )
    assert result["video_path"] == str(final_path)
    req.layer_config = {}
    monkeypatch.setattr(
        music_plan,
        "build_music_plan",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("no music")),
    )
    assert await tongjian._run_render_layers(render_id)

    production = __import__("hevi.tongjian.production", fromlist=["render_presenter_video"])
    presenter_calls: list[Path] = []

    async def fake_presenter(**kwargs: object) -> SimpleNamespace:
        presenter_calls.append(Path(str(kwargs["output_dir"])))
        return SimpleNamespace(video_path=final_path)

    monkeypatch.setattr(production, "render_presenter_video", fake_presenter)
    await tongjian._run_render(render_id)
    assert presenter_calls, (
        tongjian._context(render_id)["status"],
        tongjian._context(render_id).get("error"),
    )
    assert tongjian._context(render_id)["status"] == "COMPLETED"
    monkeypatch.setattr(
        production,
        "render_presenter_video",
        lambda **_kwargs: (_ for _ in ()).throw(production.PresenterProductionError("broken")),
    )
    failed_render_id = "tongjian-render-fail"
    failed_render = tongjian._init_run(failed_render_id, "史料")
    failed_render["run_dir"] = str(tmp_path / "failed-render")
    await tongjian._run_render(failed_render_id)
    assert tongjian._context(failed_render_id)["status"] == "FAILED"

    monkeypatch.setattr(
        script_module,
        "build_script",
        lambda **_kwargs: asyncio.sleep(0, result=(script, gate)),
    )
    regen_id = "tongjian-regenerate"
    regen = tongjian._init_run(regen_id, "史料")
    regen.update(
        {
            "status": "AWAITING_REVIEW",
            "req": req,
            "request": req,
            "chapter_ir": chapter,
            "constitution": constitution,
            "script": script,
            "run_dir": str(tmp_path / "regen"),
        }
    )
    await tongjian._regenerate_script(regen_id)
    assert regen["status"] == "AWAITING_REVIEW"
    monkeypatch.setattr(
        script_module,
        "build_script",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("regen broken")),
    )
    with pytest.raises(RuntimeError):
        await tongjian._regenerate_script(regen_id)

    assert tongjian._gate_decision(gate) == ("PASSED", None)
    assert tongjian._gate_decision({"passed": False, "errors": ["bad"]}) == ("DEGRADED", "bad")
    assert tongjian._gate_decision({"passed": False})[1]
    await tongjian._flush_run_persistence("missing")

    with pytest.raises(HTTPException):
        await tongjian.start_run(
            tongjian.RunRequest(source_name="x", raw_text=""), BackgroundTasks(), user
        )
    valid = await tongjian.start_run(
        tongjian.RunRequest(source_name="x", raw_text="原文"), BackgroundTasks(), user
    )
    assert valid["status"] == "PENDING"
    assert len(await tongjian.list_runs(user)) >= 1
    with pytest.raises(HTTPException):
        await tongjian.get_run("missing-run", user)


def test_voxcpm_worker_boundary_serializes_success_and_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise the isolated VoxCPM worker's real JSON boundary."""
    import io
    import sys
    from types import ModuleType

    import numpy as np

    from hevi.audio import voxcpm_worker as worker

    output = tmp_path / "nested" / "voice.wav"
    calls: list[dict[str, object]] = []

    class FakeModel:
        class _TTS:
            sample_rate = 16_000

        tts_model = _TTS()

        @classmethod
        def from_pretrained(cls, model_id: str, load_denoiser: bool = True) -> FakeModel:
            calls.append({"model_id": model_id, "load_denoiser": load_denoiser})
            return cls()

        def generate(self, **kwargs: object) -> np.ndarray:
            calls.append({"generate": kwargs})
            return np.zeros(32, dtype=np.float32)

        def generate_streaming(self, **kwargs: object):
            calls.append({"stream": kwargs})
            yield np.array([0.25, -0.25], dtype=np.float32)
            yield np.array([1, -1], dtype=np.int16)

    fake_voxcpm = ModuleType("voxcpm")
    fake_voxcpm.VoxCPM = FakeModel  # type: ignore[attr-defined]
    fake_soundfile = SimpleNamespace(
        write=lambda path, _audio, _rate: Path(path).write_bytes(b"wav")
    )

    def import_module(name: str) -> object:
        if name == "voxcpm":
            return fake_voxcpm
        if name == "soundfile":
            return fake_soundfile
        raise ImportError(name)

    monkeypatch.setattr(worker.importlib, "import_module", import_module)
    monkeypatch.setenv("HEVI_VOXCPM_MODEL", "test/model")

    def invoke(payload: dict[str, object]) -> int:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        return worker.main()

    assert (
        invoke(
            {
                "text": "你好",
                "output_path": str(output),
                "voice_design": "沉稳",
                "reference_audio": str(tmp_path / "missing.wav"),
            }
        )
        == 1
    )
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"ref")
    assert (
        invoke(
            {
                "text": "你好",
                "output_path": str(output),
                "voice_design": "沉稳",
                "reference_audio": str(reference),
                "kwargs": {"temperature": 0.1},
            }
        )
        == 0
    )
    assert output.read_bytes() == b"wav"
    assert calls[-1]["generate"] == {
        "text": "(沉稳)你好",
        "cfg_value": 2.0,
        "reference_wav_path": str(reference),
        "temperature": 0.1,
    }
    assert invoke({"operation": "stream", "text": "stream"}) == 0
    stream_output = capsys.readouterr().out
    assert '"status": "chunk"' in stream_output and '"status": "succeeded"' in stream_output
    assert invoke({"text": ""}) == 1
    assert invoke({"text": "value"}) == 1
    assert invoke({"text": "value", "output_path": str(output), "kwargs": "bad"}) == 1

    empty_module = ModuleType("voxcpm")
    monkeypatch.setattr(worker.importlib, "import_module", lambda _name: empty_module)
    assert invoke({"text": "value", "output_path": str(output)}) == 1
    monkeypatch.setattr(
        worker.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(RuntimeError("backend down")),
    )
    assert invoke({"text": "value", "output_path": str(output)}) == 1


@pytest.mark.asyncio
async def test_pocket_tts_native_and_optional_model_boundaries_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cover Pocket's optional model, native fallback, stream, and WAV gates."""
    import importlib as std_importlib
    from types import ModuleType

    import numpy as np

    from hevi.audio import pocket_tts_service as pocket

    real_import_module = std_importlib.import_module
    pocket._load_model.cache_clear()
    native_calls: list[dict[str, object]] = []

    def native_sync(text: str, output: Path, **kwargs: object) -> None:
        native_calls.append({"text": text, **kwargs})
        output.write_bytes(b"native-wav")

    async def native_stream(_text: str, **_kwargs: object):
        yield "native-chunk"

    monkeypatch.setattr(pocket, "_import_pocket_tts", lambda: None)
    monkeypatch.setattr("hevi.voicepro.oskill.native_voice_available", lambda: True)
    monkeypatch.setattr("hevi.voicepro.oskill.synthesize_native_voice_sync", native_sync)
    monkeypatch.setattr("hevi.voicepro.oskill.stream_native_voice", native_stream)
    assert pocket.pocket_tts_available() is True
    native_path = await pocket.synth_with_pocket_tts(
        "native", output_path=tmp_path / "native.wav", language="zh", speed=0.9
    )
    assert native_path.read_bytes() == b"native-wav" and native_calls[0]["speed"] == 0.9
    assert [chunk async for chunk in pocket.stream_pocket_tts("native stream")] == ["native-chunk"]
    monkeypatch.setattr("hevi.voicepro.oskill.native_voice_available", lambda: False)
    assert pocket.pocket_tts_available() is False
    with pytest.raises(ValueError, match="cannot be empty"):
        await pocket.synth_with_pocket_tts(" ", output_path=tmp_path / "empty.wav")
    with pytest.raises(RuntimeError, match="native voice runtime"):
        await pocket.synth_with_pocket_tts("blocked", output_path=tmp_path / "blocked.wav")

    model_calls: list[tuple[str, object]] = []

    class FakeModel:
        sample_rate = 22_050

        @classmethod
        def load_model(cls, *, config: str = "", language: str = "") -> FakeModel:
            model_calls.append(("load", {"config": config, "language": language}))
            return cls()

        def get_state_for_audio_prompt(self, voice: str) -> str:
            model_calls.append(("state", voice))
            return "state"

        def generate_audio(self, state: str, text: str) -> np.ndarray:
            model_calls.append(("generate", (state, text)))
            return np.zeros(12, dtype=np.float32)

        def generate_audio_stream(self, state: str, text: str, max_tokens: int):
            model_calls.append(("stream", (state, text, max_tokens)))
            yield np.array([0.1], dtype=np.float32)
            yield np.array([0.2], dtype=np.float32)

    fake_module = ModuleType("pocket_tts")
    fake_module.TTSModel = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setattr(pocket, "_import_pocket_tts", lambda: fake_module)
    pocket._load_model.cache_clear()
    assert pocket.pocket_tts_available() is True
    assert pocket._load_model("model.json", "zh") is not None
    assert model_calls[0] == ("load", {"config": "model.json", "language": "zh"})

    class ConfigPathModel:
        @staticmethod
        def load_model(*, config_path: str) -> object:
            model_calls.append(("config_path", config_path))
            return object()

    config_module = ModuleType("pocket_tts")
    config_module.TTSModel = ConfigPathModel  # type: ignore[attr-defined]
    monkeypatch.setattr(pocket, "_import_pocket_tts", lambda: config_module)
    pocket._load_model.cache_clear()
    assert pocket._load_model("config.yaml", "") is not None

    class NoConfigModel:
        @staticmethod
        def load_model() -> object:
            return object()

    no_config_module = ModuleType("pocket_tts")
    no_config_module.TTSModel = NoConfigModel  # type: ignore[attr-defined]
    monkeypatch.setattr(pocket, "_import_pocket_tts", lambda: no_config_module)
    pocket._load_model.cache_clear()
    with pytest.raises(RuntimeError, match="does not accept"):
        pocket._load_model("config.yaml", "")

    monkeypatch.setattr(pocket, "_load_model", lambda config: ("old", config))
    assert pocket._load_for_request("old-config", "zh") == ("old", "old-config")
    tensor_like = SimpleNamespace(
        detach=lambda: SimpleNamespace(cpu=lambda: SimpleNamespace(numpy=lambda: "array"))
    )
    assert pocket._audio_numpy(tensor_like) == "array"
    assert pocket._audio_numpy("plain") == "plain"
    scipy_output = tmp_path / "scipy.wav"
    pocket._write_wav(scipy_output, 24_000, np.zeros(4, dtype=np.float32))
    assert scipy_output.is_file()

    def fallback_import(name: str) -> object:
        if name == "scipy.io.wavfile":
            raise ImportError(name)
        if name == "soundfile":
            return SimpleNamespace(
                write=lambda path, _samples, _rate: Path(path).write_bytes(b"sf")
            )
        return real_import_module(name)

    monkeypatch.setattr(pocket.importlib, "import_module", fallback_import)
    fallback_output = tmp_path / "soundfile.wav"
    pocket._write_wav(fallback_output, 16_000, np.zeros(2, dtype=np.float32))
    assert fallback_output.read_bytes() == b"sf"
    monkeypatch.setattr(
        pocket.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("writers missing")),
    )
    with pytest.raises(RuntimeError, match="no WAV writer"):
        pocket._write_wav(tmp_path / "none.wav", 16_000, np.zeros(1))
    monkeypatch.setattr(pocket.importlib, "import_module", real_import_module)
    monkeypatch.setattr(pocket, "_import_pocket_tts", lambda: fake_module)
    monkeypatch.setattr(pocket, "_load_model", lambda *_args: FakeModel())
    model_output = tmp_path / "model.wav"
    pocket._synth_sync(
        "model",
        model_output,
        voice="alba",
        language="en",
        reference_audio=None,
        voice_design="",
        speed=1.0,
        config="",
    )
    assert model_output.is_file()
    with pytest.raises(FileNotFoundError):
        pocket._synth_sync(
            "model",
            tmp_path / "missing-ref.wav",
            voice="alba",
            language="en",
            reference_audio=tmp_path / "missing-reference.wav",
            voice_design="",
            speed=1.0,
            config="",
        )
    streamed = [chunk async for chunk in pocket.stream_pocket_tts("stream", chunk_chars=2)]
    assert len(streamed) == 2 and model_calls[-1][0] == "stream"


@pytest.mark.asyncio
async def test_tts_oprim_dispatches_all_supported_adapters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep every public TTS provider branch executable and artifact-aware."""
    import base64
    import importlib as std_importlib
    import sys
    from types import ModuleType

    import numpy as np

    from hevi.voicepro_tts import oprim as tts
    from hevi.voicepro_tts.schemas import TTSProvider, make_tts_config

    real_tts_functions = {
        name: getattr(tts, name)
        for name in (
            "synthesize_edge_tts",
            "synthesize_openai_tts",
            "synthesize_minimax_tts",
            "synthesize_cosyvoice",
            "synthesize_f5_tts",
            "synthesize_kokoro_tts",
            "synthesize_azure_tts",
        )
    }

    async def marker(*args: object, **kwargs: object) -> str:
        return f"called:{len(args)}:{len(kwargs)}"

    for provider, function_name in (
        (TTSProvider.EDGE_TTS, "synthesize_edge_tts"),
        (TTSProvider.OPEN_AI_TTS, "synthesize_openai_tts"),
        (TTSProvider.MINIMAX_TTS, "synthesize_minimax_tts"),
        (TTSProvider.COSYVOICE_TTS, "synthesize_cosyvoice"),
        (TTSProvider.F5_TTS, "synthesize_f5_tts"),
        (TTSProvider.KOKORO_TTS, "synthesize_kokoro_tts"),
        (TTSProvider.AZURE_TTS, "synthesize_azure_tts"),
    ):
        monkeypatch.setattr(tts, function_name, marker)
        assert (await tts.synthesize_tts("line", make_tts_config(provider))).startswith("called:")
    with pytest.raises(ValueError, match="不支持"):
        await tts.synthesize_tts("line", SimpleNamespace(provider="unsupported"))
    for name, function in real_tts_functions.items():
        monkeypatch.setattr(tts, name, function)

    class EdgeCommunicate:
        def __init__(self, text: str, voice: str, **kwargs: str) -> None:
            self.text, self.voice, self.kwargs = text, voice, kwargs

        async def save(self, path: str) -> None:
            Path(path).write_bytes(f"{self.text}:{self.voice}".encode())

    edge_module = ModuleType("edge_tts")
    edge_module.Communicate = EdgeCommunicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", edge_module)
    edge = await tts.synthesize_edge_tts("hi", output_path=str(tmp_path / "edge.mp3"))
    assert edge.audio_path.endswith("edge.mp3")

    class OpenAIResponse:
        def write_to_file(self, path: str) -> None:
            Path(path).write_bytes(b"openai")

    class OpenAISpeech:
        async def create(self, **_kwargs: object) -> OpenAIResponse:
            return OpenAIResponse()

    class OpenAIAudio:
        speech = OpenAISpeech()

    class AsyncOpenAI:
        audio = OpenAIAudio()

    openai_module = ModuleType("openai")
    openai_module.AsyncOpenAI = AsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    opened = await tts.synthesize_openai_tts("hi", output_path=str(tmp_path / "openai.mp3"))
    assert Path(opened.audio_path).read_bytes() == b"openai"

    class HttpResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    class HttpClient:
        body: ClassVar[dict[str, object]] = {"data": {"audio": "6869"}}

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> HttpClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> HttpResponse:
            return HttpResponse(self.body)

    monkeypatch.setenv("MINIMAX_API_KEY", "test-only")
    monkeypatch.setattr("httpx.AsyncClient", HttpClient)
    minimax = await tts.synthesize_minimax_tts("hi", output_path=str(tmp_path / "mini.mp3"))
    assert Path(minimax.audio_path).read_bytes() == b"hi"
    HttpClient.body = {"data": {"audio": base64.b64encode(b"b64").decode()}}
    minimax_b64 = await tts.synthesize_minimax_tts("hi", output_path=str(tmp_path / "mini2.mp3"))
    assert Path(minimax_b64.audio_path).read_bytes() == b"b64"
    HttpClient.body = {"data": {}}
    with pytest.raises(RuntimeError, match="did not contain"):
        await tts.synthesize_minimax_tts("hi", output_path=str(tmp_path / "bad.mp3"))

    async def cosyvoice(**kwargs: object) -> None:
        Path(str(kwargs["output_path"])).write_bytes(b"cosy")

    async def f5(**kwargs: object) -> None:
        Path(str(kwargs["output_path"])).write_bytes(b"f5")

    monkeypatch.setattr("hevi.audio.cosyvoice_service.cosyvoice_synthesize", cosyvoice)
    cosy = await tts.synthesize_cosyvoice("hi", output_path=str(tmp_path / "cosy.wav"))
    assert Path(cosy.audio_path).read_bytes() == b"cosy"
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"reference")
    monkeypatch.setenv("F5_TTS_REFERENCE_TEXT", "reference text")
    monkeypatch.setattr("hevi.audio.f5_tts_service.f5_tts_synthesize", f5)
    f5_result = await tts.synthesize_f5_tts(
        "hi", voice_ref=str(ref), output_path=str(tmp_path / "f5.wav")
    )
    assert Path(f5_result.audio_path).read_bytes() == b"f5"
    monkeypatch.delenv("F5_TTS_REFERENCE_TEXT")
    with pytest.raises(RuntimeError, match="reference audio"):
        await tts.synthesize_f5_tts("hi", output_path=str(tmp_path / "missing.wav"))

    class SoundFile:
        @staticmethod
        def write(path: str, samples: object, rate: int) -> None:
            assert rate == 24_000 and len(samples) > 0
            Path(path).write_bytes(b"kokoro")

    class KPipeline:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __call__(self, *_args: object, **_kwargs: object):
            yield (None, None, np.array([0.1, 0.2], dtype=np.float32))

    kokoro_module = ModuleType("kokoro")
    kokoro_module.KPipeline = KPipeline  # type: ignore[attr-defined]
    real_import_module = std_importlib.import_module

    def tts_import(name: str) -> object:
        if name == "soundfile":
            return SoundFile
        if name == "kokoro":
            return kokoro_module
        return real_import_module(name)

    monkeypatch.setattr(tts.importlib, "import_module", tts_import)
    kokoro = await tts.synthesize_kokoro_tts("hi", output_path=str(tmp_path / "kokoro.wav"))
    assert Path(kokoro.audio_path).read_bytes() == b"kokoro"


@pytest.mark.asyncio
async def test_digital_human_omodul_executes_registered_steps_and_media_guards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cover the presenter transaction planner and deterministic media gates."""
    from types import SimpleNamespace

    import hevi.digital_human.omodul as digital
    from hevi.digital_human.schemas import CaptionPhrase, CaptionPlan, PresenterJob

    job = PresenterJob(job_id="digital-coverage", width=640, height=360, fps=24)
    plan = digital.build_full_job_plan(job, 4.0, "render.mp4", "outputs", "demo")
    real_media_functions = {
        name: getattr(digital, name)
        for name in (
            "_calibrate_loudness",
            "_compose_timeline",
            "_burn_captions",
            "_add_keyword_effects",
        )
    }

    def adapter(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(model_dump=lambda mode="json": {"adapter": "ok", "mode": mode})

    def sync_adapter(*_args: object, **_kwargs: object) -> object:
        return Path("artifact.mp4")

    for name in (
        "_lock_content",
        "_generate_narration",
        "_calibrate_loudness",
        "generate_presenter",
        "visual_plan",
        "caption_plan",
        "_compose_timeline",
        "_burn_captions",
        "_add_keyword_effects",
        "qa_gate",
        "delivery",
    ):
        monkeypatch.setattr(digital, name, sync_adapter if name == "delivery" else adapter)
    executed = await digital.execute_plan(job, plan)
    assert len(executed["phases"]) == 5 and job.status.value == "verified"
    assert executed["phases"][0]["steps"][0]["ok"] is True
    with pytest.raises(NotImplementedError, match="no registered"):
        await digital._execute_phase(job, {"phase": "bad", "steps": [{"step": "missing"}]})
    assert digital._json_safe(Path("a/b")) == "a/b"
    assert digital._json_safe({"x": (Path("p"), 1)}) == {"x": ["p", 1]}
    for name, function in real_media_functions.items():
        monkeypatch.setattr(digital, name, function)

    source = tmp_path / "presenter.mp4"
    source.write_bytes(b"source")
    monkeypatch.setenv("HEVI_DIGITAL_HUMAN_OUTPUT_DIR", str(tmp_path / "composition"))
    monkeypatch.setattr(
        "hevi.digital_human.oprim.qa._ffprobe",
        lambda _path: {
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": "1"},
        },
    )
    assert digital._probe_composition_video(source, "presenter")["streams"]
    with pytest.raises(RuntimeError, match="missing or empty"):
        digital._probe_composition_video(tmp_path / "missing.mp4", "missing")

    def fake_ffmpeg(command: list[str], **_kwargs: object) -> SimpleNamespace:
        Path(command[-1]).write_bytes(b"encoded")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(digital.subprocess, "run", fake_ffmpeg)
    encoded = tmp_path / "encoded.mp4"
    digital._run_composition_ffmpeg(source, encoded, "encode", fps=25)
    assert encoded.read_bytes() == b"encoded"
    monkeypatch.setattr(
        digital.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="bad ffmpeg"),
    )
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        digital._run_composition_ffmpeg(source, tmp_path / "failed.mp4", "failed")

    monkeypatch.setattr(digital.subprocess, "run", fake_ffmpeg)
    job.rendered = str(source)
    job.timeline = ""
    timeline_result = digital._compose_timeline(job)
    assert Path(timeline_result["path"]).is_file() and job.rendered == timeline_result["path"]
    caption = CaptionPlan(
        phrases=[
            CaptionPhrase(text="重点", start_s=0.0, duration_s=0.5, style="radial_burst"),
            CaptionPhrase(text="普通", start_s=0.5, duration_s=0.5, style="default"),
        ]
    )
    job.caption_json = caption.model_dump_json()
    assert digital._load_caption_plan(job).is_available()
    ass_path = digital._write_caption_ass(job, caption)
    assert ass_path.is_file() and digital._ass_time(3661.25).startswith("1:")
    assert "\\{" in digital._ass_text("{safe}") and digital._filter_path(ass_path)
    burned = digital._burn_captions(job)
    assert Path(burned["path"]).is_file()
    effects = digital._add_keyword_effects(job)
    assert Path(effects["path"]).is_file() and Path(effects["report"]).is_file()
    job.final_audio = "audio.wav"
    monkeypatch.setattr(
        digital,
        "_calibrate_audio_loudness",
        lambda path, target_lufs: SimpleNamespace(path=path, target=target_lufs),
    )
    assert digital._calibrate_loudness(job).target == -16
    job.final_audio = ""
    with pytest.raises(RuntimeError, match="before narration"):
        digital._calibrate_loudness(job)


def test_watch_cli_runs_preflight_contact_sheet_and_localization_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cover the user-facing watch command without downloading remote media."""
    from hevi.ingest.video_frames import ExtractedFrame, WatchDetail
    from hevi.ingest.video_transcript import TranscriptSegment, WordSpan
    from hevi.ingest.video_watch import WatchResult
    from hevi.skills import watch_cli

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    result = WatchResult(
        source=str(source),
        frames=[ExtractedFrame(timestamp_s=0.0, path=frame)],
        transcript=[
            TranscriptSegment(
                start=0.0,
                end=0.5,
                text="嗯",
                words=(WordSpan("嗯", 0.0, 0.5),),
            ),
            TranscriptSegment(
                start=1.0,
                end=2.0,
                text="你好",
                words=(WordSpan("你", 1.0, 1.4), WordSpan("好", 1.4, 2.0)),
            ),
        ],
        duration_s=2.0,
        detail=WatchDetail.BALANCED,
        notes=["local test"],
    )
    monkeypatch.setattr(
        watch_cli,
        "check_env",
        lambda **_kwargs: SimpleNamespace(
            can_proceed=True,
            missing_binaries=["yt-dlp"],
            notes=["URL tools optional"],
        ),
    )
    monkeypatch.setattr(watch_cli, "watch_video", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(
        watch_cli,
        "build_contact_sheet",
        lambda *_args, **_kwargs: tmp_path / "contact.jpg",
    )
    assert (
        watch_cli.main(
            [
                str(source),
                "--out-dir",
                str(tmp_path / "watch"),
                "--preflight",
                "--contact-sheet",
                "--rough-cut",
                "--speakers",
                "--localize",
                "--bilingual",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "preflight: can_proceed=True" in output
    assert "contact_sheet" in output and "rough_cut" in output and "speakers" in output
    assert "localize: ass=" in output

    monkeypatch.setattr(
        watch_cli,
        "check_env",
        lambda **_kwargs: SimpleNamespace(
            can_proceed=False, missing_binaries=["ffmpeg"], notes=["missing ffmpeg"]
        ),
    )
    assert watch_cli.main(["https://example.test/video", "--preflight"]) == 2
    assert "missing: ffmpeg" in capsys.readouterr().out

    localize_calls: list[dict[str, object]] = []

    async def localize(
        _config: dict[str, object], _input: dict[str, object], output_dir: Path
    ) -> dict[str, object]:
        localize_calls.append({"output_dir": output_dir})
        return {
            "status": "succeeded",
            "report_path": str(tmp_path / "localize.json"),
            "findings": {"output_video_path": str(tmp_path / "localized.mp4")},
        }

    monkeypatch.setattr(
        watch_cli,
        "check_env",
        lambda **_kwargs: SimpleNamespace(can_proceed=True, missing_binaries=[], notes=[]),
    )
    monkeypatch.setattr("hevi.production.media_workflows.video_localization_workflow", localize)
    assert watch_cli.main(["https://example.test/video", "--localize", "--execute-localize"]) == 3
    assert "localize-error" in capsys.readouterr().err
    assert (
        watch_cli.main(
            [
                str(source),
                "--localize",
                "--execute-localize",
                "--dub",
                "--target-language",
                "en-US",
            ]
        )
        == 0
    )
    assert localize_calls and localize_calls[-1]["output_dir"] == Path(".hevi_watch")
    assert "localized_video" in capsys.readouterr().out

    async def failed_localize(
        _config: dict[str, object], _input: dict[str, object], _output_dir: Path
    ) -> dict[str, object]:
        return {"status": "failed", "error": "provider unavailable", "report_path": "report"}

    monkeypatch.setattr(
        "hevi.production.media_workflows.video_localization_workflow", failed_localize
    )
    assert watch_cli.main([str(source), "--localize", "--execute-localize"]) == 3
    assert "provider unavailable" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_agentic_montage_runtime_covers_resume_gates_and_local_artifact_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise the OpenMontage-style transaction around explicit HEVI gates."""
    from hevi.montage.omodul import agentic
    from hevi.montage.schemas import ArtifactType

    assert agentic._mapping(SimpleNamespace(value=1))["value"] == 1
    assert agentic._mapping(object()) == {}
    config = {"pipeline": "animated-explainer", "manifest_path": str(tmp_path / "pipeline.yaml")}
    assert agentic._manifest_path(config).name == "pipeline.yaml"
    fingerprint = agentic._safe_fingerprint(
        "demo", {"caller": object(), "budget_usd": 1}, {"topic": "x", "renderer": object()}
    )
    assert len(fingerprint) == 24
    events: list[dict[str, object]] = []

    async def async_notify(event: dict[str, object]) -> None:
        events.append(event)

    await agentic._notify(async_notify, {"stage": "x"})
    await agentic._notify(None, {"stage": "ignored"})
    assert events == [{"stage": "x"}]

    async def handler(_data: dict[str, object], _context: dict[str, object]) -> dict[str, object]:
        return {"status": "ok", "value": 1}

    assert await agentic._custom_or("x", lambda *_args: {"value": 2}, {}, {}, {}) == {"value": 2}
    assert await agentic._custom_or("x", handler, {}, {}, {"x": handler}) == {
        "status": "ok",
        "value": 1,
    }
    assert (await agentic._custom_or("x", lambda *_args: "bad", {}, {}, {}))["status"] == "failed"

    beats = SimpleNamespace(status="ok", reason="", payload={"beats": ["look"]})

    async def beats_tool(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return beats

    monkeypatch.setattr("hevi.studio.tools.invoke_tool", beats_tool)
    designed = await agentic._character_design(
        {"topic": "history", "character_ids": ["hero"], "character_style": "ink"}, {}
    )
    assert designed["character_design"]["subjects"] == ["hero"]

    async def blocked_beats(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status="blocked", reason="no beats", payload={})

    monkeypatch.setattr("hevi.studio.tools.invoke_tool", blocked_beats)
    assert (await agentic._character_design({"topic": "history"}, {}))["status"] == "blocked"

    material = tmp_path / "material.mp4"
    material.write_bytes(b"media")
    monkeypatch.setattr(
        agentic,
        "stage_assets",
        lambda *_args, **_kwargs: asyncio.sleep(
            0,
            result={
                "ranked_materials": [
                    {"cached_path": str(material)},
                    {"url": "https://example.invalid/remote.mp4"},
                    "ignored",
                ],
                "bound_assets": ["bound"],
            },
        ),
    )
    assets = await agentic._assets({"media_path": str(material)}, {})
    assert assets["asset_manifest"]["verified_files"] == [str(material)]
    assert assets["asset_manifest"]["unresolved"] == ["https://example.invalid/remote.mp4"]

    monkeypatch.setattr(
        agentic,
        "stage_script",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={"script_lines": ["line"]}),
    )
    assert (await agentic._script({}, {}))["script"]["line_count"] == 1
    monkeypatch.setattr(
        agentic,
        "stage_edit_plan",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={"edit_plan": {"cuts": 1}}),
    )
    assert (await agentic._edit({}, {}))["edit_decisions"] == {"cuts": 1}

    final = tmp_path / "final.mp4"
    final.write_bytes(b"final")

    async def invoke_tool(name: str, payload: dict[str, object]) -> SimpleNamespace:
        if name == "timeline.create":
            return SimpleNamespace(
                status="ok", reason="", payload={"timeline": {"timeline_id": "t1"}}
            )
        if name == "timeline.export":
            return SimpleNamespace(status="ok", reason="", payload={"video_path": str(final)})
        raise AssertionError(name)

    monkeypatch.setattr("hevi.studio.tools.invoke_tool", invoke_tool)
    monkeypatch.setattr(
        "hevi.production.delivery_gate.probe_video",
        lambda _path: SimpleNamespace(
            has_video=True, has_audio=True, duration_s=2.0, size_bytes=final.stat().st_size
        ),
    )
    composed = await agentic._compose(
        {"topic": "history", "edit_plan": {"cuts": 1}, "require_audio": True}, {}
    )
    assert composed["status"] == "completed" and composed["render_report"]["quality"]["passed"]
    no_plan = await agentic._compose({"topic": "history"}, {})
    assert no_plan["status"] == "blocked"

    async def blocked_tool(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status="ok", reason="", payload={})

    monkeypatch.setattr("hevi.studio.tools.invoke_tool", blocked_tool)
    no_timeline = await agentic._compose({"edit_plan": {"cuts": 1}}, {})
    assert no_timeline["status"] == "blocked"

    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    checkpoint_path = checkpoint_dir / "research.json"
    agentic._checkpoint(
        checkpoint_path, "demo", "research", {"research": {"context": "facts"}}, approval="pending"
    )
    trail: list[dict[str, Any]] = []
    assert agentic._load_resume_data(checkpoint_dir, ["research"], {}, trail) == set()
    agentic._approve_checkpoints(checkpoint_dir, {"research"}, trail)
    data: dict[str, Any] = {}
    assert agentic._load_resume_data(checkpoint_dir, ["research"], data, trail) == {"research"}
    assert data["research"]["context"] == "facts"
    assert any(item["event"] == "checkpoint_approved" for item in trail)
    assert ArtifactType.CHECKPOINT.value == "checkpoint"

    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    monkeypatch.setattr(
        "hevi.montage.oprim.analyze_reference_video",
        lambda _path: SimpleNamespace(model_dump=lambda mode="json": {"content": "review"}),
    )
    monkeypatch.setattr("hevi.montage.oprim.sample_frames", lambda _path: ["frame"])
    monkeypatch.setattr("hevi.montage.oprim.extract_transcript", lambda _path: ["line"])
    prepared: dict[str, Any] = {"media_path": str(reference)}
    agentic._prepare_reference_media(prepared)
    assert prepared["source_media_review"]["content"] == "review" and prepared[
        "reference_frames"
    ] == ["frame"]
