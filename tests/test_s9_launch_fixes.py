"""S9 上线阻断修复的回归测试（Whisper 路径 / 首发白名单 / 多行脚本 / 下载边界）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hevi.core.asr_paths import resolve_whisper_model


def test_asr_resolver_prefers_existing_env_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = tmp_path / "fw-model"
    model.mkdir()
    monkeypatch.setenv("HEVI_WHISPER_MODEL", str(model))
    monkeypatch.delenv("FASTER_WHISPER_MODEL_DIR", raising=False)
    assert resolve_whisper_model() == str(model.resolve())


def test_asr_resolver_accepts_model_name_and_raises_chinese(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEVI_WHISPER_MODEL", "small")
    assert resolve_whisper_model() == "small"

    from hevi.core import asr_paths

    monkeypatch.setattr(asr_paths, "_DEFAULT_DIRS", ())
    for key in ("FASTER_WHISPER_MODEL_DIR", "HEVI_WHISPER_MODEL", "HEVI_TALKCRAFT_WHISPER"):
        monkeypatch.setenv(key, "/nonexistent/whisper")
    with pytest.raises(FileNotFoundError) as err:
        resolve_whisper_model()
    assert "找不到可用的 faster-whisper 模型" in str(err.value)
    assert resolve_whisper_model(required=False) is None


def test_launch_whitelist_labels_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.studio.recipes import get_recipe, launch_lines, launch_strict, line_availability

    monkeypatch.delenv("HEVI_LAUNCH_LINES", raising=False)
    monkeypatch.delenv("HEVI_LAUNCH_STRICT", raising=False)
    assert "collage_broll" in launch_lines()
    assert line_availability("collage_broll") == "ga"
    assert line_availability("explainer") == "internal"
    assert get_recipe("explainer").to_dict()["availability"] == "internal"
    assert launch_strict() is False

    monkeypatch.setenv("HEVI_LAUNCH_LINES", "explainer")
    assert line_availability("explainer") == "ga"
    assert line_availability("koubo_cut") == "internal"
    monkeypatch.setenv("HEVI_LAUNCH_STRICT", "1")
    assert launch_strict() is True


def test_zero_input_derives_queries_for_all_query_lines() -> None:
    from hevi.studio.fulfill import _zero_input

    for line in ("explainer", "cinematic", "director_pipeline", "history_scene"):
        data = _zero_input({"line_id": line, "topic": "橘猫看海"}, line)
        assert data["texts"], line
        assert len(data["queries"]) >= len(data["texts"]), line


def test_zero_input_derives_reference_offsets(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.studio import fulfill

    monkeypatch.setattr(fulfill, "_media_duration", lambda _p: 12.0)
    data = fulfill._zero_input(
        {"line_id": "reference_adapt", "media_path": "/tmp/ref.mp4", "topic": "橘猫看海"},
        "reference_adapt",
    )
    assert data["texts"]
    assert len(data["offsets"]) == len(data["texts"])
    assert data["offsets"][0] == 0.0


def test_multiline_script_is_split_before_text_measurement() -> None:
    from hevi.koubo_cut.pipeline import _flatten_line, _script_lines

    lines = _script_lines(
        script_text="第一句。\n第二句\n第三句！",
        script_lines=["甲句。\n乙句。"],
        topic="",
    )
    assert "\n" not in "".join(lines)
    assert "甲句。" in lines and "乙句。" in lines
    assert _flatten_line("没标点\n第二行") == ["没标点", "第二行"]


def test_koubo_wrap_never_measures_multiline(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    from hevi.koubo_cut.pipeline import _font, _wrap

    img = Image.new("RGB", (400, 200))
    draw = ImageDraw.Draw(img)
    lines = _wrap(draw, "第一行\n第二行", _font(40), 300)
    assert lines
    assert all("\n" not in line for line in lines)


def test_koubo_fit_audio_honours_target(tmp_path: Path) -> None:
    from hevi.koubo_cut.pipeline import _fit_audio, _speech_duration

    src = tmp_path / "in.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", "-ar", "44100", "-ac", "2", str(src)],
        check=True,
    )
    fitted, duration = _fit_audio(src, tmp_path / "out.wav", 2.0)
    assert fitted != src
    assert duration <= 2.05
    assert _speech_duration(fitted) <= 2.05


def test_artifact_download_stays_inside_output_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from hevi.api.routers.studio import _resolve_artifact

    monkeypatch.setenv("HEVI_OUTPUT_ROOT", str(tmp_path))
    good = tmp_path / "clip.mp4"
    good.write_bytes(b"not-a-real-mp4")
    assert _resolve_artifact(str(good)) == good.resolve()

    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(HTTPException) as err:
        _resolve_artifact(str(outside))
    assert err.value.status_code == 403

    bad_type = tmp_path / "secret.env"
    bad_type.write_text("x")
    with pytest.raises(HTTPException) as err:
        _resolve_artifact(str(bad_type))
    assert err.value.status_code == 415


def test_retention_timestamp_survives_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.scheduler.service import SchedulerService

    state = tmp_path / "last-run"
    state.write_text("1700000000\n")
    monkeypatch.setenv("HEVI_OUTPUT_RETENTION_STATE", str(state))

    class Repo:
        async def acquire_leader(self, *a, **k):  # pragma: no cover - not called
            return False

    svc = SchedulerService(Repo())
    assert svc._last_retention == 1700000000.0
    svc._write_last_retention(1800000000)
    assert SchedulerService(Repo())._last_retention == 1800000000.0


def test_conform_duration_pads_and_trims(tmp_path: Path) -> None:
    from hevi.studio.fulfill import _conform_duration

    short = tmp_path / "short.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=15:d=2",
         "-f", "lavfi", "-i", "anullsrc=r=22050:cl=stereo", "-t", "2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(short)],
        check=True,
    )
    _conform_duration(short, 30.0, 3.0)
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(short)],
        text=True,
    ).strip()
    assert abs(float(out) - 30.0) < 0.5
