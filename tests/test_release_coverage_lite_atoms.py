"""Offline coverage for Lite media atoms and their fail-closed boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from hevi.pipeline_lite.oprim import oprim_asr as asr
from hevi.pipeline_lite.oprim import oprim_broll as broll
from hevi.pipeline_lite.oprim import oprim_ffmpeg as ffmpeg
from hevi.pipeline_lite.oprim import oprim_visual_scenes as scenes
from hevi.pipeline_lite.schemas import LiteCue


def _cues() -> list[LiteCue]:
    return [
        LiteCue(index=3, narration="第一句旁白"),
        LiteCue(index=4, narration="第二句旁白内容"),
    ]


@pytest.mark.asyncio
async def test_asr_live_adapter_and_fallback_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "master.wav"
    audio.write_bytes(b"wav")
    monkeypatch.setattr(asr, "_probe_duration", lambda _path: 4.0)

    async def vibevoice(
        *_args: object, **_kwargs: object
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return (
            [
                {"start": 0.2, "end": 1.3, "text": "识别一", "words": []},
                {"start": 1.3, "end": 4.0, "text": "识别二", "words": []},
            ],
            [{"start": 0.2, "end": 1.3, "text": "识别一"}],
        )

    monkeypatch.setattr(asr, "_vibevoice_transcribe", vibevoice)
    output = tmp_path / "timestamps.json"
    aligned = await asr.extract_segment_timestamps(
        audio, _cues(), output, asr_engine="vibevoice", hotwords=["专名"]
    )
    assert aligned[0]["index"] == 3
    assert aligned[0]["start"] == pytest.approx(0.2)
    json_text = output.read_text(encoding="utf-8")
    assert json_text
    assert '"duration": 4.0' in json_text

    async def unavailable(
        *_args: object, **_kwargs: object
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return [], []

    def whisper(*_args: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return ([{"start": 0.0, "end": 4.0, "text": "整段"}], [])

    monkeypatch.setattr(asr, "_vibevoice_transcribe", unavailable)
    monkeypatch.setattr(asr, "_whisper_transcribe", whisper)
    fallback = await asr.extract_segment_timestamps(audio, _cues(), asr_engine="auto")
    assert [item["index"] for item in fallback] == [3, 4]
    assert fallback[-1]["end"] == 4.0

    forced_fallback = await asr.extract_segment_timestamps(audio, _cues(), asr_engine="vibevoice")
    assert forced_fallback[0]["start"] == 0.0
    assert forced_fallback[-1]["end"] == 4.0


@pytest.mark.asyncio
async def test_asr_http_adapter_and_timestamp_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "master.wav"
    audio.write_bytes(b"wav")

    class FakeResponse:
        def __init__(self, status_code: int, payload: object) -> None:
            self.status_code = status_code
            self.payload = payload

        def json(self) -> object:
            if isinstance(self.payload, BaseException):
                raise self.payload
            return self.payload

    class FakeClient:
        response = FakeResponse(
            200,
            {
                "utterances": [
                    {"start": "0.1", "end": "0.8", "text": " 有效 ", "speaker": "A"},
                    {"start": 1, "end": 2, "text": ""},
                ]
            },
        )

        def __init__(self, **_kwargs: object) -> None:
            self.request: tuple[str, object, object] | None = None

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, path: str, *, files: object, data: object) -> FakeResponse:
            self.request = (path, files, data)
            return self.response

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    segments, words = await asr._vibevoice_transcribe(audio, hotwords=["词"], language="zh")
    assert segments == [{"start": 0.1, "end": 0.8, "text": "有效", "speaker": "A"}]
    assert words == [{"start": 0.1, "end": 0.8, "text": "有效"}]

    FakeClient.response = FakeResponse(503, {})
    assert await asr._vibevoice_transcribe(audio) == ([], [])
    FakeClient.response = FakeResponse(200, ValueError("bad json"))
    assert await asr._vibevoice_transcribe(audio) == ([], [])
    assert await asr._vibevoice_transcribe(tmp_path / "missing.wav") == ([], [])

    cues = _cues()
    assert asr._align([], cues, 4.0)[-1]["end"] == 4.0
    assert (
        asr._align(
            [
                {"start": 0, "end": 1, "words": [{"text": "词"}]},
                {"start": 1, "end": 2, "words": []},
            ],
            cues,
            4.0,
        )[0]["text"]
        == cues[0].narration
    )
    assert asr._split_words_proportional("  one two  ", 0.0, 2.0)[-1]["end"] == 2.0
    assert len(asr._split_words_proportional("连续中文文本", 0.0, 2.0)) == 2
    assert asr._split_words_proportional("   ", 0.0, 2.0) == []


def test_asr_duration_probe_success_and_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "master.wav"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="2.25"),
    )
    assert asr._probe_duration(audio) == 2.25

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=""),
    )
    assert asr._probe_duration(audio) == 3.0
    monkeypatch.setattr(
        subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())
    )
    assert asr._probe_duration(audio) == 3.0


def test_visual_scene_resolution_and_all_renderers() -> None:
    assert scenes.resolve_scene(0, {"scene": "fire", "_scene_locked": True}) == "fire"
    assert scenes.resolve_scene(0, {"scene": "fire"}, "") == "hook_cave"
    assert scenes.resolve_scene(0, {"title": "控火之争"}) == "fire"
    assert scenes.resolve_scene(1, {"visual_query": "stone tool"}) == "tools"
    assert scenes.resolve_scene(2, {"eyebrow": "migration"}) == "migrate"
    assert scenes.resolve_scene(5, {}, "一个完全没有关键词的普通句子") == "close"

    expected = {
        "hook_cave",
        "identity",
        "timeline",
        "place",
        "dig",
        "anatomy",
        "tools",
        "fire",
        "hunt",
        "migrate",
        "lost",
        "close",
        "unknown",
    }
    rendered = {scene: scenes.build_visual_html(scene, title="<标题>") for scene in expected}
    assert all('class="viz' in html for html in rendered.values())
    assert "viz-default" in rendered["unknown"]
    assert scenes._s("unused") == ""

    assert scenes.assign_scenes_to_cues(
        [
            {"index": 0, "narration": "控火", "props": {}},
            {"index": 1, "narration": "时间", "props": {}},
        ]
    ) == ["fire", "timeline"]


def test_ffmpeg_mux_and_audio_track_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video = tmp_path / "video.mp4"
    audio = tmp_path / "voice.wav"
    bgm = tmp_path / "bgm.mp3"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    bgm.write_bytes(b"bgm")

    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _name: None)
    assert ffmpeg.mux_audio_video(video, audio, tmp_path / "degraded.mp4") == video

    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _name: "tool")
    real_assert_audio_track = ffmpeg.assert_audio_track
    monkeypatch.setattr(ffmpeg, "assert_audio_track", lambda _path: True)

    commands: list[list[str]] = []

    def successful_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"muxed")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(ffmpeg.subprocess, "run", successful_run)
    output = tmp_path / "muxed.mp4"
    assert ffmpeg.mux_audio_video(video, audio, output, bgm_path=bgm, bgm_volume=0.2) == output
    assert output.read_bytes() == b"muxed"
    assert "-filter_complex" in commands[-1]

    original = tmp_path / "original.mp4"
    original.write_bytes(b"video")
    plain = tmp_path / "plain.mp4"
    assert ffmpeg.mux_audio_video(original, audio, plain, remove_original=True) == plain
    assert not original.exists()
    assert "-filter_complex" not in commands[-1]

    monkeypatch.setattr(
        ffmpeg.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="bad", stdout=""),
    )
    with pytest.raises(ffmpeg.MuxError, match="混流失败"):
        ffmpeg.mux_audio_video(video, audio, tmp_path / "failed.mp4")

    monkeypatch.setattr(ffmpeg, "assert_audio_track", real_assert_audio_track)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _name: None)
    assert ffmpeg.assert_audio_track(video)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda _name: "ffprobe")
    monkeypatch.setattr(
        ffmpeg.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="1\n"),
    )
    assert ffmpeg.assert_audio_track(video)
    monkeypatch.setattr(
        ffmpeg.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(ffmpeg.MuxError, match="缺少音频轨"):
        ffmpeg.assert_audio_track(video)


@pytest.mark.asyncio
async def test_broll_fail_closed_response_and_client_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self, response: httpx.Response | BaseException) -> None:
            self.response = response

        async def get(self, *_args: object, **_kwargs: object) -> httpx.Response:
            if isinstance(self.response, BaseException):
                raise self.response
            return self.response

    monkeypatch.setenv("PEXELS_API_KEY", "env-key")
    assert await broll.fetch_broll_video_url("science", client=Client(httpx.Response(401))) is None
    assert await broll.fetch_broll_video_url("science", client=Client(httpx.Response(500))) is None
    assert (
        await broll.fetch_broll_video_url("science", client=Client(httpx.ConnectError("offline")))
        is None
    )
    assert (
        await broll.fetch_broll_video_url(
            "science", client=Client(httpx.Response(200, content=b"not-json"))
        )
        is None
    )

    payload = {
        "videos": [
            None,
            {"id": None, "url": "https://source/skip"},
            {"id": 1, "url": "https://source/skip", "video_files": []},
            {
                "id": 2,
                "url": "https://source/hls",
                "video_files": [{"file_type": "application/x-mpegURL", "link": "hls"}],
            },
            {
                "id": 3,
                "url": "https://source/ok",
                "video_files": [{"file_type": "video/mp4; codecs=avc1", "link": "mp4"}],
            },
        ]
    }
    items = await broll.fetch_broll_video_url(
        "science", count=0, orientation=None, client=Client(httpx.Response(200, json=payload))
    )
    assert items and items[0]["external_id"] == "3"
    assert items[0]["title"] == "science · Pexels"

    class ManagedClient(Client):
        async def __aenter__(self) -> ManagedClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        broll.httpx,
        "AsyncClient",
        lambda **_kwargs: ManagedClient(
            httpx.Response(
                200,
                json={
                    "videos": [
                        {
                            "id": 4,
                            "url": "https://source/managed",
                            "video_files": [{"file_type": "video/mp4", "link": "managed.mp4"}],
                        }
                    ]
                },
            )
        ),
    )
    managed = await broll.fetch_broll_video_url("managed", api_key="explicit", client=None)
    assert managed and managed[0]["preview_url"] == "managed.mp4"
