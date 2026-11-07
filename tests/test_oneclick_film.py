"""Offline contract tests for story.oneclick_film.

Every paid/external stage is monkeypatched (same style as
tests/test_story_film.py): no key, no network.  The ffmpeg mixing in
the music-success test runs for real on a silent wav, and the rig test
composites the real expression-rig face onto real PNG backgrounds.
"""

import asyncio
import json
import subprocess
import wave
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.storyfilm import oneclick, pipeline
from hevi.storyfilm.pipeline import infer_beat_emotion

DRAFT = {
    "title": "咪咪回家",
    "hook": "雨夜里，咪咪能找回家吗？",
    "characters": [
        {
            "name": "咪咪",
            "role": "主角",
            "appearance_en": "a small orange tabby kitten with a red collar",
        }
    ],
    "beats": [
        {
            "narration": "雨下得很大，咪咪冒雨走在回家的路上，冷得直发抖。",
            "visual_en": "a kitten alone in the rain at night",
            "motion_prompt": "slow push-in",
        },
        {
            "narration": "忽然，它看见远处有一盏温暖的灯光在晃动。",
            "visual_en": "a warm lamp glowing far away",
            "motion_prompt": "gentle pan right",
        },
        {
            "narration": "咪咪鼓起勇气跑过小桥，灯下就是它的家。",
            "visual_en": "a kitten running across a small bridge",
            "motion_prompt": "static warm close-up",
        },
    ],
}


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def test_resolve_preset_valid_and_copy() -> None:
    cfg = oneclick.resolve_preset("tuantuan")
    assert cfg["visual"] == "rig"
    assert cfg["rig_character"] == "tuantuan"
    cfg["visual"] = "mutated"
    assert oneclick.PRESETS["tuantuan"]["visual"] == "rig"
    for name in ("storybook", "tuantuan", "cinema", "watercolor"):
        assert oneclick.resolve_preset(name)["style"]


def test_resolve_preset_invalid_lists_valid() -> None:
    with pytest.raises(ValueError) as excinfo:
        oneclick.resolve_preset("bogus")
    for name in ("storybook", "tuantuan", "cinema", "watercolor"):
        assert name in str(excinfo.value)


def test_preset_music_products_are_legal() -> None:
    from hevi.audio.score_render import PRODUCT_MAP, TEMPLATES

    for name, cfg in oneclick.PRESETS.items():
        assert cfg["music_product"] in PRODUCT_MAP, name
        if cfg.get("music_style"):
            assert cfg["music_style"] in TEMPLATES, name


# ---------------------------------------------------------------------------
# infer_beat_emotion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "beat,expected",
    [
        ({"narration": "咪咪很难过，眼泪不停地往下掉。"}, "sad"),
        ({"narration": "前面好像有危险，它害怕极了。"}, "scared"),
        ({"narration": "忽然，远处亮起了一盏灯。"}, "surprised"),
        ({"narration": "它开心地笑了起来。"}, "happy"),
        ({"narration": "终于成功了，它回到家啦。"}, "joy"),
        ({"narration": "它想了想，为什么灯还亮着呢？"}, "thinking"),
        ({"narration": "清晨，河边安安静静的。"}, "neutral"),
        ({"visual_en": "a scared kitten in danger"}, "scared"),
    ],
)
def test_infer_beat_emotion_mappings(beat: dict, expected: str) -> None:
    from hevi.layer4_legacy.handdraw.expression_rig import EMOTIONS

    got = infer_beat_emotion(beat)
    assert got == expected
    assert got in EMOTIONS


# ---------------------------------------------------------------------------
# boost_ken_burns
# ---------------------------------------------------------------------------


def test_boost_ken_burns_zoom_and_pan() -> None:
    zoom = {"kind": "zoom_in", "crop_w_start": 0.92, "crop_w_end": 0.50,
            "cx_start": 0.5, "cx_end": 0.5}
    boosted = oneclick.boost_ken_burns(zoom)
    assert abs(boosted["crop_w_start"] - boosted["crop_w_end"]) > abs(
        zoom["crop_w_start"] - zoom["crop_w_end"]
    )
    assert boosted["crop_w_start"] > boosted["crop_w_end"]  # direction kept
    assert zoom["crop_w_start"] == 0.92  # input not mutated
    assert oneclick.boost_ken_burns(zoom) == boosted  # pure / deterministic

    pan = {"kind": "pan_right", "crop_w_start": 0.62, "crop_w_end": 0.62,
           "cx_start": 0.12, "cx_end": 0.88}
    boosted_pan = oneclick.boost_ken_burns(pan)
    assert (boosted_pan["cx_start"], boosted_pan["cx_end"]) == (0.0, 1.0)
    assert boosted_pan["crop_w_start"] == boosted_pan["crop_w_end"] == 0.62


# ---------------------------------------------------------------------------
# Oneclick orchestration (inner pipeline faked)
# ---------------------------------------------------------------------------


def _patch_inner_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gates: dict,
    stages: dict | None = None,
    cost: float = 1.234,
) -> dict:
    calls: dict = {}

    async def fake_run_story_film(**kwargs):
        calls["kwargs"] = kwargs
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "film.mp4").write_bytes(b"mp4bytes")
        (out_dir / "narration.wav").write_bytes(b"RIFFfake")
        shots = [
            {
                "shot_id": "S01",
                "narration": "第一镜。",
                "duration_s": 6.0,
                "motion_prompt": "slow push-in",
                "ken_burns": pipeline.ken_burns_params("slow push-in", 0),
                "image": str(out_dir / "images" / "shot_01.png"),
            },
            {
                "shot_id": "S02",
                "narration": "第二镜。",
                "duration_s": 6.0,
                "motion_prompt": "gentle pan right",
                "ken_burns": pipeline.ken_burns_params("gentle pan right", 1),
                "image": str(out_dir / "images" / "shot_02.png"),
            },
        ]
        (out_dir / "shots.json").write_text(
            json.dumps(shots, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "gates.json").write_text(
            json.dumps(gates, ensure_ascii=False), encoding="utf-8"
        )
        delivery = {
            "title": "测试片",
            "total_cost_usd": cost,
            "stages": stages
            or {"story": {"status": "ok"}, "render": {"status": "ok"}},
            "film": {"path": str(out_dir / "film.mp4"), "duration_s": 12.0},
            "film_audio": str(out_dir / "narration.wav"),
            "gates": gates,
        }
        (out_dir / "delivery.json").write_text(
            json.dumps(delivery, ensure_ascii=False), encoding="utf-8"
        )
        return delivery

    monkeypatch.setattr(oneclick, "run_story_film", fake_run_story_film)
    return calls


class _FakeReviewResult:
    qa = {"pass": True, "report": "/job/review_sheet/review_sheet.json",
          "comments": 1}


def _patch_review_sheet_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    real_get = caps.get

    class FakeCap:
        def render_safe(self, params, out_dir, *, duration, aspect, seed):
            return _FakeReviewResult()

    def fake_get(name):
        if name == "qa.review_sheet":
            return FakeCap()
        return real_get(name)

    monkeypatch.setattr(caps, "get", fake_get)


_PASS_GATES = {
    "film_gate": {"verdict": "pass", "gate_light": "green"},
    "earshot_gate": {"pass": True},
}


def test_oneclick_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _patch_inner_pipeline(monkeypatch, gates=_PASS_GATES)
    _patch_review_sheet_ok(monkeypatch)
    out_dir = tmp_path / "job"
    ledger = oneclick.run_oneclick_film(
        "一只小猫在雨夜里找回家的路", preset="storybook", out_dir=out_dir
    )
    assert ledger["status"] == "delivered"
    assert ledger["cost_usd"] == pytest.approx(1.234)
    assert ledger["film"]["duration_s"] == 12.0
    assert ledger["film"]["path"].endswith("film.mp4")
    assert ledger["retries"] == []
    assert ledger["degradations"] == []
    assert ledger["gates"]["review_sheet"]["pass"] is True
    assert ledger["stages"]["render"] == "ok"
    on_disk = json.loads(
        (out_dir / "oneclick_delivery.json").read_text(encoding="utf-8")
    )
    assert on_disk == ledger
    kwargs = calls["kwargs"]
    assert kwargs["render_route"] == "hyperframes"
    assert kwargs["music"] is True
    assert kwargs["music_product"] == "cute"
    assert "rig_character" not in kwargs


def test_oneclick_tuantuan_preset_passes_rig(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _patch_inner_pipeline(monkeypatch, gates=_PASS_GATES)
    _patch_review_sheet_ok(monkeypatch)
    oneclick.run_oneclick_film(
        "团团的一天", preset="tuantuan", out_dir=tmp_path / "job"
    )
    assert calls["kwargs"]["rig_character"] == "tuantuan"


def test_oneclick_film_gate_red_retries_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    red_gates = {
        "film_gate": {"verdict": "red", "gate_light": "red"},
        "earshot_gate": {"pass": True},
    }
    _patch_inner_pipeline(monkeypatch, gates=red_gates)
    _patch_review_sheet_ok(monkeypatch)
    renders: list = []

    def fake_render(*, shots, title, narration_path, output_path, **_):
        renders.append(shots)
        Path(output_path).write_bytes(b"mp4v2")
        return 12.0

    monkeypatch.setattr(oneclick, "render_motion_film", fake_render)
    gate_calls = {"n": 0}

    def fake_gates(film, out, *, aspect):
        gate_calls["n"] += 1
        return {
            "film_gate": {"verdict": "pass", "gate_light": "green"},
            "earshot_gate": {"pass": True},
        }

    monkeypatch.setattr(oneclick, "_run_gates", fake_gates)
    out_dir = tmp_path / "job"
    ledger = oneclick.run_oneclick_film(
        "前提", preset="storybook", out_dir=out_dir
    )
    assert gate_calls["n"] == 1
    assert len(renders) == 1
    assert len(ledger["retries"]) == 1
    assert ledger["retries"][0]["gate"] == "film_gate"
    assert ledger["gates"]["film_gate"]["verdict"] == "pass"
    assert ledger["status"] == "delivered"
    boosted = renders[0][0]["ken_burns"]
    original = pipeline.ken_burns_params("slow push-in", 0)
    assert abs(boosted["crop_w_start"] - boosted["crop_w_end"]) > abs(
        original["crop_w_start"] - original["crop_w_end"]
    )


def test_oneclick_earshot_fail_retries_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gates = {
        "film_gate": {"verdict": "pass", "gate_light": "green"},
        "earshot_gate": {"pass": False},
    }
    _patch_inner_pipeline(monkeypatch, gates=gates)
    _patch_review_sheet_ok(monkeypatch)
    gain_calls: list = []
    monkeypatch.setattr(
        oneclick,
        "apply_gain_control",
        lambda path, **kw: gain_calls.append((path, kw)) or {},
    )

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **_):
        Path(cmd[-1]).write_bytes(b"media")
        return _Proc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        oneclick,
        "_run_gates",
        lambda film, out, *, aspect: {
            "film_gate": {"verdict": "pass", "gate_light": "green"},
            "earshot_gate": {"pass": True},
        },
    )
    ledger = oneclick.run_oneclick_film(
        "前提", preset="storybook", out_dir=tmp_path / "job"
    )
    earshot_retries = [r for r in ledger["retries"] if r["gate"] == "earshot_gate"]
    assert len(earshot_retries) == 1
    assert gain_calls and gain_calls[0][1].get("target_dbtp") == -2.5
    assert ledger["gates"]["earshot_gate"]["pass"] is True
    assert ledger["status"] == "delivered"


def test_oneclick_review_sheet_missing_is_skipped_not_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_inner_pipeline(monkeypatch, gates=_PASS_GATES)
    monkeypatch.setattr(caps, "names", lambda: [])
    ledger = oneclick.run_oneclick_film(
        "前提", preset="storybook", out_dir=tmp_path / "job"
    )
    assert "skipped" in ledger["gates"]["review_sheet"]
    assert any(
        d["stage"] == "review_sheet" for d in ledger["degradations"]
    )
    assert ledger["status"] == "delivered_with_warnings"


# ---------------------------------------------------------------------------
# Pipeline-level: music degradation + success + rig mode
# ---------------------------------------------------------------------------


def _patch_all_stages(monkeypatch: pytest.MonkeyPatch) -> dict:
    from hevi.audio import (
        forced_alignment,
        lux_tts_service,
        tts_alignment,
        whisper_alignment,
    )
    from hevi.image import gpt_image_service

    monkeypatch.delenv("HEVI_TTS_ALIGNMENT_PROVIDER", raising=False)
    calls: dict = {"render_audio": []}

    async def fake_story(premise, *, style, max_shots):
        return json.loads(json.dumps(DRAFT)), 0.0022

    monkeypatch.setattr(pipeline, "generate_story", fake_story)

    async def fake_generate(*, prompt, output_path, size="1024x1536", **_):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"pngbytes")
        return {"output_path": str(output_path), "cost": 0.0107}

    async def fake_edit(*, image_paths, prompt, output_path, size="1024x1536", **_):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"pngbytes")
        return {"output_path": str(output_path), "cost": 0.023}

    monkeypatch.setattr(gpt_image_service, "gpt_image_generate", fake_generate)
    monkeypatch.setattr(gpt_image_service, "gpt_image_edit", fake_edit)
    monkeypatch.setattr(lux_tts_service, "lux_tts_available", lambda: True)

    async def fake_synth(*, text, output_path, voice=None, **_):
        Path(output_path).write_bytes(b"RIFFfake")
        return Path(output_path)

    monkeypatch.setattr(lux_tts_service, "synth_with_luxtts", fake_synth)

    async def fake_align(*, audio_path, text, **_):
        full = "".join(b["narration"] for b in DRAFT["beats"])
        chars = list(pipeline.normalize_text(full))
        words = tuple(
            tts_alignment.WordTiming(c, i * 100, i * 100 + 90)
            for i, c in enumerate(chars)
        )
        return words, 0.0012

    monkeypatch.setattr(forced_alignment, "forced_align_words", fake_align)

    async def fake_whisper_align(*, audio_path, text, **_):
        words, _paid = await fake_align(audio_path=audio_path, text=text)
        return words, None

    monkeypatch.setattr(
        whisper_alignment, "whisper_align_words", fake_whisper_align
    )
    monkeypatch.setattr(tts_alignment, "probe_duration_ms", lambda p: 3200)
    monkeypatch.setattr(
        pipeline,
        "apply_gain_control",
        lambda path, **_: {
            "peak_before_dbtp": 0.1,
            "peak_after_dbtp": -1.5,
            "gain_db": -1.6,
            "method": "volume",
        },
    )

    def fake_render(*, shots, title, narration_path, output_path, **_):
        calls["render_audio"].append(str(narration_path))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"mp4bytes")
        return sum(float(s["duration_s"]) for s in shots)

    monkeypatch.setattr(pipeline, "render_motion_film", fake_render)
    monkeypatch.setattr(
        pipeline,
        "_run_gates",
        lambda film, out, *, aspect: {"film_gate": {"verdict": "pass"}},
    )
    return calls


def test_pipeline_music_failure_degrades_not_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all_stages(monkeypatch)
    from hevi.audio import score_render

    def boom(*args, **kwargs):
        raise RuntimeError("score boom")

    monkeypatch.setattr(score_render, "generate_score", boom)
    out_dir = tmp_path / "job"
    delivery = asyncio.run(
        pipeline.run_story_film(
            premise="一只小猫在雨夜里找回家的路",
            max_shots=3,
            out_dir=out_dir,
            music=True,
        )
    )
    assert delivery["stages"]["music"]["status"] == "degraded"
    assert "score boom" in delivery["stages"]["music"]["error"]
    assert (out_dir / "film.mp4").is_file()
    assert delivery["film_audio"].endswith("narration.wav")


def test_pipeline_music_success_mixes_soundtrack(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _patch_all_stages(monkeypatch)
    from hevi.audio import lux_tts_service

    async def fake_synth_wav(*, text, output_path, voice=None, **_):
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x00" * 22050 * 2)
        return Path(output_path)

    monkeypatch.setattr(lux_tts_service, "synth_with_luxtts", fake_synth_wav)
    out_dir = tmp_path / "job"
    delivery = asyncio.run(
        pipeline.run_story_film(
            premise="一只小猫在雨夜里找回家的路",
            max_shots=3,
            out_dir=out_dir,
            music=True,
        )
    )
    assert delivery["stages"]["music"]["status"] == "ok"
    for name in ("bgm.wav", "bgm_sidecar.json", "soundtrack.wav"):
        assert (out_dir / name).is_file(), name
    assert delivery["music"]["note_count"] > 0
    assert delivery["film_audio"].endswith("soundtrack.wav")
    assert calls["render_audio"][-1].endswith("soundtrack.wav")


def test_pipeline_rig_mode_composites_faces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all_stages(monkeypatch)
    from PIL import Image

    from hevi.image import gpt_image_service
    from hevi.layer4_legacy.handdraw.expression_rig import EMOTIONS

    async def fake_generate_png(*, prompt, output_path, size="1024x1536", **_):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (256, 384), (120, 160, 200)).save(output_path)
        return {"output_path": str(output_path), "cost": 0.01}

    monkeypatch.setattr(
        gpt_image_service, "gpt_image_generate", fake_generate_png
    )
    out_dir = tmp_path / "job"
    delivery = asyncio.run(
        pipeline.run_story_film(
            premise="团团的一天",
            max_shots=3,
            out_dir=out_dir,
            rig_character="tuantuan",
        )
    )
    assert delivery["stages"]["images"]["status"] == "ok"
    assert not (out_dir / "images" / "character.png").exists()
    shots = json.loads((out_dir / "shots.json").read_text(encoding="utf-8"))
    assert len(shots) == 3
    for shot in shots:
        assert shot["emotion"] in EMOTIONS
        with Image.open(shot["image"]) as img:
            assert img.size == (256, 384)
    assert shots[1]["emotion"] == "surprised"  # 忽然…


def test_pipeline_default_no_music_no_rig_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all_stages(monkeypatch)
    out_dir = tmp_path / "job"
    delivery = asyncio.run(
        pipeline.run_story_film(
            premise="一只小猫在雨夜里找回家的路",
            max_shots=3,
            out_dir=out_dir,
        )
    )
    assert "music" not in delivery["stages"]
    assert delivery["film_audio"].endswith("narration.wav")
    shots = json.loads((out_dir / "shots.json").read_text(encoding="utf-8"))
    assert all("emotion" not in s for s in shots)
    assert (out_dir / "images" / "character.png").is_file()


# ---------------------------------------------------------------------------
# Capability registration + CLI
# ---------------------------------------------------------------------------


def test_oneclick_capability_registered() -> None:
    assert "story.oneclick_film" in caps.names()
    listed = [c.name for c in caps.list(kind="line")]
    assert "story.oneclick_film" in listed


def test_oneclick_capability_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("story.oneclick_film")
    for params in (
        {},
        {"premise": ""},
        {"premise": "x", "preset": "bogus"},
        {"premise": "x", "max_shots": 9},
        {"premise": "x", "unknown_key": 1},
    ):
        with pytest.raises(CapabilityError):
            cap.render_safe(
                params, tmp_path / "bad", duration=0.0, aspect="9:16", seed=1
            )


def test_oneclick_capability_render_happy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_inner_pipeline(monkeypatch, gates=_PASS_GATES)
    _patch_review_sheet_ok(monkeypatch)
    cap = caps.get("story.oneclick_film")
    result = cap.render_safe(
        {"premise": "一只小猫在雨夜里找回家的路", "preset": "cinema"},
        tmp_path / "job",
        duration=0.0,
        aspect="9:16",
        seed=3,
    )
    assert result.mp4 and Path(result.mp4).is_file()
    assert result.duration_s == 12.0
    assert result.qa["status"] == "delivered"
    assert result.qa["preset"] == "cinema"
    assert result.qa["total_cost_usd"] == pytest.approx(1.234)


def test_oneclick_cli_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MONID_API_KEY", "dummy-for-cli-test")

    def fake_oneclick(premise, **kwargs):
        return {
            "film": {"path": "/x/film.mp4", "duration_s": 3.0},
            "cost_usd": 0.5,
            "gates": {},
            "status": "delivered",
        }

    monkeypatch.setattr(oneclick, "run_oneclick_film", fake_oneclick)
    assert oneclick.main(["一个前提", "--out", str(tmp_path / "o")]) == 0

    def boom(premise, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(oneclick, "run_oneclick_film", boom)
    assert oneclick.main(["一个前提", "--out", str(tmp_path / "o2")]) == 2
