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
from typing import Any

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
