"""Contract tests for story.film_from_prompt (CAPABILITY_CONTRACT.md).

Offline: every paid/external stage is monkeypatched, so no key and no
network are needed. The pure-function tests pin the story-draft validation,
the beat-to-word timing map and the PixStag handoff shape.
"""

import json
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError
from hevi.storyfilm import pipeline
from hevi.storyfilm.pipeline import (
    NARRATION_MAX_CHARS,
    NARRATION_MIN_CHARS,
    StoryFilmError,
    build_frame_html,
    build_pixstag_package,
    check_measured_duration,
    choose_mastering,
    compute_gain_db,
    estimate_narration_seconds,
    ken_burns_params,
    map_beats_to_words,
    narration_char_count,
    parse_continuation_beats,
    parse_story_draft,
    trim_draft_to_max_chars,
)

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
# Registry contract
# ---------------------------------------------------------------------------


def test_story_film_registered_and_listable() -> None:
    assert "story.film_from_prompt" in caps.names()
    listed = [c.name for c in caps.list(kind="line")]
    assert "story.film_from_prompt" in listed


def test_story_film_describe_has_schema_and_description() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    assert "story.film_from_prompt" in by_name
    assert by_name["story.film_from_prompt"].get("description")


def test_story_film_rejects_invalid_params() -> None:
    cap = caps.get("story.film_from_prompt")
    bad_params = [
        {},  # missing premise
        {"premise": ""},
        {"premise": "x", "render_route": "bogus"},
        {"premise": "x", "max_shots": 2},  # below image-budget floor
        {"premise": "x", "max_shots": 9},  # above budget cap
        {"premise": "x", "unknown_key": 1},
    ]
    for params in bad_params:
        with pytest.raises(CapabilityError):
            cap.render_safe(
                params, Path("/tmp/sf-bad"), duration=0.0, aspect="9:16", seed=1
            )


def test_story_film_missing_monid_key_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    cap = caps.get("story.film_from_prompt")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"premise": "一只小猫在雨夜里找回家的路"},
            tmp_path / "out",
            duration=0.0,
            aspect="9:16",
            seed=1,
        )


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def test_parse_story_draft_accepts_plain_and_fenced_json() -> None:
    raw = json.dumps(DRAFT, ensure_ascii=False)
    draft = parse_story_draft(raw, max_shots=3)
    assert draft["title"] == "咪咪回家"
    assert len(draft["beats"]) == 3
    fenced = parse_story_draft(f"```json\n{raw}\n```", max_shots=3)
    assert fenced["title"] == "咪咪回家"


def test_parse_story_draft_rejects_garbage_and_overflow() -> None:
    with pytest.raises(StoryFilmError):
        parse_story_draft("not json at all", max_shots=3)
    with pytest.raises(StoryFilmError):
        parse_story_draft(json.dumps(DRAFT, ensure_ascii=False), max_shots=2)
    no_char = dict(DRAFT, characters=[])
    with pytest.raises(StoryFilmError):
        parse_story_draft(json.dumps(no_char, ensure_ascii=False), max_shots=3)


def test_map_beats_to_words_spans() -> None:
    from hevi.audio.tts_alignment import WordTiming

    full = "".join(b["narration"] for b in DRAFT["beats"])
    chars = list(pipeline.normalize_text(full))
    words = tuple(
        WordTiming(c, i * 100, i * 100 + 90) for i, c in enumerate(chars)
    )
    spans = map_beats_to_words([b["narration"] for b in DRAFT["beats"]], list(words))
    assert len(spans) == 3
    assert spans[0][0] == 0
    assert spans[0][1] < spans[1][0] <= spans[1][1] < spans[2][0] <= spans[2][1]
    assert spans[2][1] == (len(chars) - 1) * 100 + 90


def test_map_beats_to_words_exhaustion_fails() -> None:
    from hevi.audio.tts_alignment import WordTiming

    with pytest.raises(StoryFilmError):
        map_beats_to_words(["一句很长很长的话"], [WordTiming("一", 0, 90)])


def test_build_frame_html_has_image_and_subtitle(tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"png")
    doc = build_frame_html(img, "咪咪跑过小桥。", title="咪咪回家")
    assert img.as_uri() in doc
    assert "咪咪跑过小桥。" in doc
    assert "咪咪回家" in doc
    doc2 = build_frame_html(img, "只有字幕。")
    assert 'class="title"' not in doc2


def test_build_pixstag_package_shape() -> None:
    shots = [
        {
            "shot_id": "S01",
            "first_frame": "/job/images/shot_01.png",
            "motion_prompt": "slow push-in",
            "duration_s": 3.5,
            "narration": "雨下得很大。",
            "image": "/job/images/shot_01.png",
        }
    ]
    pkg = build_pixstag_package(
        premise="一只小猫在雨夜里找回家的路",
        draft=DRAFT,
        shots=shots,
        aspect="9:16",
        narration_path=Path("/job/narration.wav"),
        alignment_path=Path("/job/alignment.json"),
    )
    assert pkg["kind"] == "pixstag_shot_package"
    only = pkg["shots"][0]
    assert only["first_frame"].endswith("shot_01.png")
    assert only["motion_prompt"] == "slow push-in"
    assert only["duration_s"] == 3.5


# ---------------------------------------------------------------------------
# Full render wiring (all external stages monkeypatched)
# ---------------------------------------------------------------------------


def _patch_all_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    from hevi.audio import forced_alignment, lux_tts_service, tts_alignment
    from hevi.image import gpt_image_service

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
    monkeypatch.setattr(
        tts_alignment, "probe_duration_ms", lambda p: 3200
    )

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
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"mp4bytes")
        return sum(float(s["duration_s"]) for s in shots)

    monkeypatch.setattr(pipeline, "render_motion_film", fake_render)
    monkeypatch.setattr(
        pipeline, "_run_gates",
        lambda film, out, *, aspect: {"film_gate": {"verdict": "green"}},
    )


def test_story_film_render_hyperframes_writes_all_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all_stages(monkeypatch)
    cap = caps.get("story.film_from_prompt")
    out_dir = tmp_path / "job"
    result = cap.render_safe(
        {"premise": "一只小猫在雨夜里找回家的路", "max_shots": 3},
        out_dir,
        duration=0.0,
        aspect="9:16",
        seed=5,
    )
    assert result.mp4 and Path(result.mp4).is_file()
    assert result.duration_s > 0
    assert result.qa["title"] == "咪咪回家"
    assert result.qa["stages"]["render"] == "ok"
    # 0.0022 story + 0.0107 key still + 3 x 0.023 edits + 0.0012 alignment = 0.0831
    assert result.qa["total_cost_usd"] == pytest.approx(0.0831, abs=1e-4)

    for name in (
        "story.json", "story.md", "characters.json", "shots.json",
        "narration.wav", "alignment.json", "gates.json", "delivery.json",
        "job.json",
    ):
        assert (out_dir / name).is_file(), name
    shots = json.loads((out_dir / "shots.json").read_text(encoding="utf-8"))
    assert len(shots) == 3
    for shot in shots:
        assert shot["first_frame"].endswith(".png")
        assert shot["motion_prompt"]
        assert shot["duration_s"] > 0
        assert shot["end_ms"] > shot["start_ms"]
        # motion injection: every shot carries Ken Burns parameters and
        # the parameters actually move (start != end in crop or centre)
        kb = shot["ken_burns"]
        assert kb["kind"] in ("zoom_in", "zoom_out", "pan_left", "pan_right")
        assert kb["crop_w_start"] != kb["crop_w_end"] or (
            kb["cx_start"] != kb["cx_end"]
        )
    delivery = json.loads((out_dir / "delivery.json").read_text(encoding="utf-8"))
    assert delivery["mastering"]["gain_db"] == -1.6
    assert "duration_check" in delivery
    assert "story_length" in delivery

    Path(result.mp4).unlink()
    assert not Path(result.mp4).exists(), (
        "contract: deleting the artifact must break verification"
    )


def test_story_film_render_pixstag_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_all_stages(monkeypatch)
    cap = caps.get("story.film_from_prompt")
    out_dir = tmp_path / "job2"
    result = cap.render_safe(
        {
            "premise": "一只小猫在雨夜里找回家的路",
            "max_shots": 3,
            "render_route": "pixstag_package",
        },
        out_dir,
        duration=0.0,
        aspect="9:16",
        seed=5,
    )
    assert result.qa["pixstag_package"] and Path(result.qa["pixstag_package"]).is_file()
    assert not (out_dir / "film.mp4").exists()
    pkg = json.loads(Path(result.qa["pixstag_package"]).read_text(encoding="utf-8"))
    assert pkg["kind"] == "pixstag_shot_package"
    assert len(pkg["shots"]) == 3
    assert result.qa["stages"]["gates"] == "skipped"


# ---------------------------------------------------------------------------
# Duration enforcement (narration length / continuation / trim)
# ---------------------------------------------------------------------------


def test_narration_char_count_and_estimate() -> None:
    # Pilot baseline: 138 chars -> 21.849 s at the measured speech rate.
    assert narration_char_count(DRAFT) == sum(
        len(b["narration"]) for b in DRAFT["beats"]
    )
    assert estimate_narration_seconds(138) == pytest.approx(21.849, abs=0.01)
    assert estimate_narration_seconds(NARRATION_MIN_CHARS) >= 35.0
    assert estimate_narration_seconds(NARRATION_MAX_CHARS) <= 50.0


def test_parse_continuation_beats_accepts_and_rejects() -> None:
    beats = parse_continuation_beats(
        json.dumps(
            {"beats": [{"narration": "咪咪继续往前跑", "visual_en": "kitten runs",
                         "motion_prompt": "tracking"}]},
            ensure_ascii=False,
        )
    )
    assert beats[0]["narration"].endswith("。")
    with pytest.raises(StoryFilmError):
        parse_continuation_beats("not json")
    with pytest.raises(StoryFilmError):
        parse_continuation_beats('{"beats": []}')


def test_trim_draft_to_max_chars_keeps_first_and_last() -> None:
    long_beat = "咪" * 69 + "。"
    draft = {
        "title": "长稿",
        "beats": [{"narration": long_beat} for _ in range(5)],
    }
    trimmed = trim_draft_to_max_chars(draft, max_chars=300)
    assert narration_char_count(trimmed) <= 300
    assert len(trimmed["beats"]) >= 3
    assert trimmed["beats"][0] is draft["beats"][0] or (
        trimmed["beats"][0]["narration"] == long_beat
    )
    assert trimmed["beats"][-1]["narration"] == long_beat


@pytest.mark.asyncio
async def test_generate_story_continues_until_min_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    filler = (
        "咪咪踩着湿漉漉的小路继续往前跑，雨点落在它的耳朵上，"
        "它却只想着妈妈做的热牛奶和门口那盏灯，它加快脚步往前跑。"
    )

    async def fake_chat(messages, *, max_tokens=1400):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(DRAFT, ensure_ascii=False), 0.002
        beats = [
            {"narration": filler, "visual_en": "kitten keeps searching",
             "motion_prompt": "slow push-in"}
            for _ in range(3)
        ]
        return json.dumps({"beats": beats}, ensure_ascii=False), 0.001

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    draft, cost = await pipeline.generate_story(
        "一只小猫在雨夜里找回家的路", style="s", max_shots=3
    )
    assert narration_char_count(draft) >= NARRATION_MIN_CHARS
    assert draft["_continuation_rounds"] >= 1
    assert "_length_warning" not in draft
    # the original ending beat is still the ending
    assert draft["beats"][-1]["narration"] == DRAFT["beats"][-1]["narration"]
    assert cost == pytest.approx(0.003, abs=1e-6)


@pytest.mark.asyncio
async def test_generate_story_trims_overlong_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_draft = json.loads(json.dumps(DRAFT))
    for beat in long_draft["beats"]:
        beat["narration"] = "咪" * 69 + "。"
    long_draft["beats"] += [
        {"narration": "咪" * 69 + "。", "visual_en": "x",
         "motion_prompt": "slow push-in"},
        {"narration": "尾" * 69 + "。", "visual_en": "y",
         "motion_prompt": "slow push-in"},
    ]

    async def fake_chat(messages, *, max_tokens=1400):
        return json.dumps(long_draft, ensure_ascii=False), 0.002

    monkeypatch.setattr(pipeline, "_chat_completion", fake_chat)
    draft, _ = await pipeline.generate_story("前提", style="s", max_shots=5)
    assert narration_char_count(draft) <= NARRATION_MAX_CHARS
    assert draft["beats"][-1]["narration"].startswith("尾")


def test_check_measured_duration_records_pilot_miss_and_pass() -> None:
    miss = check_measured_duration(21849)  # pilot_cat measured narration
    assert miss["target_met"] is False
    assert miss["reason"]
    ok = check_measured_duration(42000)
    assert ok["target_met"] is True
    assert ok["reason"] == ""


# ---------------------------------------------------------------------------
# Audio mastering (pure gain math + applied mastering with faked measure)
# ---------------------------------------------------------------------------


def test_compute_gain_db_attenuates_only() -> None:
    assert compute_gain_db(0.1) == -1.6  # pilot peak +0.1 -> target -1.5
    assert compute_gain_db(0.0) == -1.5
    assert compute_gain_db(-1.5) == 0.0
    assert compute_gain_db(-3.0) == 0.0  # never boost


def test_choose_mastering_volume_vs_loudnorm_vs_none() -> None:
    plan = choose_mastering(0.1, -12.7)  # pilot: -1.6 dB -> LUFS -14.3, in tol
    assert plan == {"method": "volume", "gain_db": -1.6}
    loud = choose_mastering(0.5, -15.5)  # -2.0 dB would push LUFS to -17.5
    assert loud["method"] == "loudnorm"
    assert choose_mastering(-2.0, -12.0)["method"] == "none"


def test_apply_gain_control_none_and_volume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wav = tmp_path / "n.wav"
    wav.write_bytes(b"RIFFfake")
    measures = iter(
        [
            {"true_peak_dbtp": -2.0, "lufs": -13.0},
        ]
    )
    monkeypatch.setattr(pipeline, "_measure_audio", lambda p: next(measures))
    info = pipeline.apply_gain_control(wav)
    assert info["method"] == "none"
    assert info["peak_after_dbtp"] == -2.0

    wav.write_bytes(b"RIFFfake")
    seq = iter(
        [
            {"true_peak_dbtp": 0.1, "lufs": -12.7},
            {"true_peak_dbtp": -1.5, "lufs": -14.3},
        ]
    )
    monkeypatch.setattr(pipeline, "_measure_audio", lambda p: next(seq))

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **_):
        Path(cmd[-1]).write_bytes(b"RIFFmastered")
        return _Proc()

    monkeypatch.setattr("subprocess.run", fake_run)
    info = pipeline.apply_gain_control(wav)
    assert info["method"] == "volume"
    assert info["gain_db"] == -1.6
    assert info["peak_after_dbtp"] == -1.5
    assert info["lufs_after"] == -14.3
    assert wav.read_bytes() == b"RIFFmastered"


# ---------------------------------------------------------------------------
# Ken Burns motion parameters
# ---------------------------------------------------------------------------


def test_ken_burns_params_move_for_every_prompt_kind() -> None:
    push = ken_burns_params("slow push-in", 0)
    assert push["kind"] == "zoom_in"
    assert push["crop_w_start"] > push["crop_w_end"]
    pan = ken_burns_params("gentle pan left", 1)
    assert pan["kind"] == "pan_left"
    assert pan["cx_start"] > pan["cx_end"]
    # even a 'static' prompt must move — film_gate rejects static shots
    static = ken_burns_params("static wide shot", 2)
    assert static["crop_w_start"] != static["crop_w_end"]
    for i, prompt in enumerate(
        ["tracking shot", "pull out", "close-up", "something else"]
    ):
        kb = ken_burns_params(prompt, i)
        assert kb["crop_w_start"] != kb["crop_w_end"] or (
            kb["cx_start"] != kb["cx_end"]
        )
