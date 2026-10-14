"""Real acceptance tests for the registered Handdraw capabilities."""
from __future__ import annotations

import io
import json
import random
import subprocess
import sys
import wave
import zipfile
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from skimage.metrics import structural_similarity

import hevi.capabilities as caps
import hevi.layer4_legacy.handdraw.tts as tts
from hevi.capabilities.registry import CapabilityError
from hevi.layer4_legacy.handdraw.illustrator import build_scene_illustration
from hevi.layer4_legacy.handdraw.kids_storyboards import (
    UnsupportedKidsTopicError,
    select_kids_storyboard,
    validate_kids_on_screen_text,
    validate_kids_script,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "hevi" / "layer4_legacy" / "handdraw" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from narration_master import load_master  # noqa: E402


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "/home/soffy/.local/bin/ffprobe",
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_registry_lists_handdraw_capabilities() -> None:
    names = caps.names()
    assert {
        "handdraw.full",
        "handdraw.storyboard",
        "handdraw.narration",
        "handdraw.illustration",
    } <= set(names)
    assert any(c.name == "handdraw.full" for c in caps.list(kind="line"))
    assert len(caps.list(aspect="9:16")) >= 4


def test_render_entrypoint_normalizes_all_schema_errors(tmp_path: Path) -> None:
    cap = caps.get("handdraw.full")
    with pytest.raises(CapabilityError):
        cap.validate_params({})
    with pytest.raises(CapabilityError):
        cap.render({}, tmp_path, duration=2.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render(
            {"topic": "短题", "aspect": "16:9", "style_id": "99"},
            tmp_path,
            duration=2.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render(
            {"topic": "小狐狸", "aspect": "16:9"},
            tmp_path,
            duration=float("nan"),
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render(
            {"topic": "小狐狸", "aspect": "16:9"},
            tmp_path,
            duration=2.0,
            aspect="4:3",
            seed=1,
        )


def test_kids_storyboards_are_topic_grounded_and_have_required_arc() -> None:
    brushing = select_kids_storyboard("为什么要刷牙")
    sharing = select_kids_storyboard("小狐狸学会轮流")
    assert brushing["topic_key"] == "brush_teeth"
    assert sharing["topic_key"] == "fox_turn_taking"
    assert len(brushing["pages"]) == 4
    assert [b["stage"] for p in brushing["pages"] for b in p["beats"]] == brushing["stages"]
    report = validate_kids_script(
        brushing["title"],
        brushing["pages"],
        aspect="9:16",
        caption_font_size=60,
    )
    assert report["passed"], report
    assert report["human_review"] == "pending"
    adult = validate_kids_script(
        "复利效应",
        sharing["pages"],
        aspect="16:9",
        caption_font_size=56,
    )
    assert not adult["passed"]
    assert "复利" in adult["blocked_terms_found"]


def test_illustration_seed_reproduces_png_and_alpha_stays_transparent(tmp_path: Path) -> None:
    cap = caps.get("handdraw.illustration")
    params = {"topic": "小狐狸学会轮流", "aspect": "16:9", "style_id": "17"}
    first = cap.render(params, tmp_path / "seed-a", duration=0, aspect="16:9", seed=724)
    second = cap.render(params, tmp_path / "seed-b", duration=0, aspect="16:9", seed=724)
    other = cap.render(params, tmp_path / "seed-c", duration=0, aspect="16:9", seed=725)
    assert first.png and second.png and other.png
    assert first.png.is_file() and second.png.is_file() and other.png.is_file()
    assert first.sha256 == second.sha256
    assert first.sha256 != other.sha256
    with Image.open(first.png) as image:
        assert image.mode == "RGBA"
        assert image.getextrema()[3][0] == 0, "the illustration canvas must remain transparent outside drawn shapes"


def test_four_style_recipes_are_visibly_distinct_and_transparent(tmp_path: Path) -> None:
    styles = ("1", "8", "10", "17")
    raw_images = []
    for style in styles:
        path = tmp_path / f"fox-style-{style}.png"
        meta = build_scene_illustration(
            "fox_share", path, style_id=style, size=(800, 800), seed=11
        )
        assert path.is_file() and path.stat().st_size > 1000
        assert len(meta["parts"]) >= 5
        raw_images.append(np.asarray(Image.open(path).convert("RGBA")))

    union = np.logical_or.reduce([img[:, :, 3] > 5 for img in raw_images])
    ys, xs = np.where(union)
    crop = (
        slice(max(0, int(ys.min()) - 8), min(union.shape[0], int(ys.max()) + 9)),
        slice(max(0, int(xs.min()) - 8), min(union.shape[1], int(xs.max()) + 9)),
    )
    display_images = []
    paper = np.asarray((253, 251, 247), dtype=np.float32)
    for image in raw_images:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        rgb = np.rint(image[:, :, :3] * alpha + paper * (1.0 - alpha)).astype(np.uint8)
        display_images.append(rgb[crop])
        assert image[0, 0, 3] == 0, "no opaque square backdrop"

    measured = {}
    for i, left in enumerate(styles):
        for j in range(i + 1, len(styles)):
            right = styles[j]
            score = structural_similarity(
                display_images[i],
                display_images[j],
                channel_axis=2,
                data_range=255,
            )
            measured[f"{left}-{right}"] = float(score)
    assert len(measured) == 6
    assert max(measured.values()) < 0.85, measured


def test_thirty_random_sample_count_narrations_round_trip_through_load_master(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for sample-count range ends that previously rounded past EOF."""
    rng = random.Random(20261014)
    lengths_by_text: dict[str, int] = {}

    def fake_synthesis(
        text: str,
        out_wav: Path,
        cache_dir: Path,
        *,
        engine: str,
        length_scale: float,
        cosy_wav: Path | None,
    ) -> None:
        del cache_dir, engine, length_scale, cosy_wav
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        frames = lengths_by_text[text]
        # A non-silent deterministic signal in PCM16 at the master's rate.
        signal = (np.arange(frames, dtype=np.int32) % 2 * 800 - 400).astype("<i2")
        with wave.open(str(out_wav), "wb") as stream:
            stream.setparams((1, 2, tts.SAMPLE_RATE, 0, "NONE", "not compressed"))
            stream.writeframes(signal.tobytes())

    monkeypatch.setattr(tts, "_synth_with_cache", fake_synthesis)
    for case in range(30):
        root = tmp_path / f"round-trip-{case:02d}"
        root.mkdir()
        count = rng.randint(2, 8)
        beats = []
        for index in range(count):
            text = f"随机时长样本{case:02d}-{index:02d}"
            lengths_by_text[text] = rng.randint(400, tts.SAMPLE_RATE * 2)
            beats.append({"id": f"b{index:02d}", "text": text})
        tts.build_narration_master(
            beats,
            root,
            pause_gap=rng.randint(1, 400) / tts.SAMPLE_RATE,
            prefer_cosy=False,
            use_asr=False,
        )
        manifest = {
            "narration": {"source": "master.wav", "alignment": "alignment.json"},
            "audio": {
                "pace": 1,
                "trim_silence": False,
                "sentence_pause_seconds": 0,
                "page_pause_seconds": 0,
            },
            "pages": [{"beats": beats}],
        }
        samples, aligned, report = load_master(root, manifest, root / "normalized.wav")
        assert len(samples) == report["samples"]
        assert len(aligned) == count
        last = aligned[beats[-1]["id"]]
        assert last["end"] <= len(samples) / tts.SAMPLE_RATE
        assert last["end"] == last["end_samples"] / tts.SAMPLE_RATE


def test_cosyvoice_is_one_batched_request_and_never_reuses_whole_wav_per_beat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    body = io.BytesIO()
    with zipfile.ZipFile(body, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(2):
            audio = io.BytesIO()
            rng = np.random.default_rng(index)
            samples = rng.integers(-3000, 3000, size=12000, dtype=np.int16).astype("<i2")
            with wave.open(audio, "wb") as stream:
                stream.setparams((1, 2, tts.SAMPLE_RATE, 0, "NONE", "not compressed"))
                stream.writeframes(samples.tobytes())
            archive.writestr(f"beat-{index:02d}.wav", audio.getvalue())
    payload = body.getvalue()
    seen: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return payload

    def fake_urlopen(request, timeout):
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data.decode("utf-8"))
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out_dir = tmp_path / "batch"
    out_dir.mkdir()
    paths = tts._synth_cosyvoice_batch(["一句旁白", "第二句旁白"], out_dir)
    assert paths is not None and len(paths) == 2
    assert all(path.is_file() and path.stat().st_size > 1024 for path in paths)
    assert seen["timeout"] >= 300
    assert len(seen["payload"]["script"]) == 2

    # A concatenated master has no safe per-beat boundaries; use one engine for
    # the complete film instead of silently repeating the entire WAV per sentence.
    wav = io.BytesIO()
    with wave.open(wav, "wb") as stream:
        stream.setparams((1, 2, tts.SAMPLE_RATE, 0, "NONE", "not compressed"))
        stream.writeframes(np.full(6000, 400, dtype="<i2").tobytes())
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: type(
        "Response", (), {"__enter__": lambda self: self, "__exit__": lambda self, *_x: False, "read": lambda self: wav.getvalue()}
    )())
    assert tts._synth_cosyvoice_batch(["一句", "二句"], out_dir) is None


def test_capability_preview_contract_returns_a_real_three_second_mp4() -> None:
    from hevi.api.routers.capabilities import (
        CapabilityPreviewRequest,
        list_capability_contracts,
        render_capability_preview,
    )

    payload = list_capability_contracts()
    names = {item["name"] for item in payload["items"]}
    assert "handdraw.full" in names
    response = render_capability_preview(
        "handdraw.full",
        CapabilityPreviewRequest(
            topic="小狐狸学会轮流",
            aspect="16:9",
            style_id="17",
            hand_preset="navy",
            seed=20261014,
        ),
    )
    path = Path(response.path)
    assert path.is_file() and path.stat().st_size > 1000
    assert response.media_type == "video/mp4"
    assert response.headers["x-capability-duration"] == "3.000"
    probe = _probe(path)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)
    assert abs(float(probe["format"]["duration"]) - 3.0) <= 0.1


def test_seed_reproduces_real_preview_mp4(
    tmp_path: Path,
    handdraw_preview,
) -> None:
    second = caps.get("handdraw.full").render(
        {
            "topic": "小狐狸学会轮流",
            "aspect": "16:9",
            "style_id": "17",
            "hand_preset": "navy",
        },
        tmp_path / "same-seed-second-render",
        duration=2.0,
        aspect="16:9",
        seed=20261014,
    )
    assert second.mp4 and second.mp4.is_file()
    assert second.sha256 == handdraw_preview.result.sha256



def test_four_preschool_topics_generate_distinct_narration_and_reject_adult_topics(
    tmp_path: Path,
) -> None:
    cases = [
        ("小兔子学会分享", "分享"),
        ("为什么要刷牙", "刷牙"),
        ("小猫学会过马路", "过马路"),
        ("为什么要洗手", "洗手"),
    ]
    audio_hashes = []
    scripts = []
    for index, (topic, required_word) in enumerate(cases):
        storyboard = select_kids_storyboard(topic)
        narration = "".join(beat["text"] for page in storyboard["pages"] for beat in page["beats"])
        assert required_word in narration, {"topic": topic, "narration": narration}
        assert storyboard["title"] == topic
        scripts.append(narration)
        matching_line = next(
            beat["text"] for page in storyboard["pages"] for beat in page["beats"]
            if required_word in beat["text"]
        )
        out_dir = tmp_path / f"narration-{index}"
        out_dir.mkdir()
        master, _alignment, _duration = tts.build_narration_master(
            [{"id": f"topic-{index}", "text": matching_line}],
            out_dir,
            prefer_cosy=False,
            use_asr=False,
        )
        assert master.is_file() and master.stat().st_size > 1000
        audio_hashes.append(tts.sha256_file(master))
    assert len(set(scripts)) == 4
    assert len(set(audio_hashes)) == 4, audio_hashes
    with pytest.raises(UnsupportedKidsTopicError, match="不适合"):
        select_kids_storyboard("复利效应与巴菲特")
    with pytest.raises(UnsupportedKidsTopicError, match="暂不支持"):
        select_kids_storyboard("小猫学会量子金融")
    with pytest.raises(CapabilityError, match="不适合"):
        caps.get("handdraw.full").render(
            {"topic": "复利效应与巴菲特", "aspect": "16:9", "style_id": "17", "hand_preset": "navy"},
            tmp_path / "adult-topic-rejected",
            duration=2.0,
            aspect="16:9",
            seed=1,
        )


def test_kids_gate_fails_closed_when_preview_audio_measurements_are_missing() -> None:
    storyboard = select_kids_storyboard("小狐狸学会轮流")
    report = validate_kids_script(
        storyboard["title"], storyboard["pages"], aspect="16:9",
        caption_font_size=56, characters_per_second=3.0, preview=True,
        audio_lufs=None, true_peak_dbtp=None, require_audio_measurements=True,
    )
    assert not report["passed"]
    assert not report["checks"]["audio_measurements_present"]
    assert not report["checks"]["integrated_loudness_minus_16_plus_minus_1_lufs"]
    assert not report["checks"]["true_peak_at_or_below_minus_1_5_dbtp"]
    visible = validate_kids_on_screen_text(["一起学小办法", "深入机制分析"])
    assert not visible["passed"]
    assert "深入机制分析" in visible["blocked_terms_found"]


def test_caption_groups_preserve_chinese_words_and_punctuation() -> None:
    text = "牙齿上有小小的碎屑，大家都能玩。"
    tokens = tts._caption_tokens(text)
    assert "小小的" in tokens
    assert "碎屑" in tokens
    assert "大家都能" in tokens
    char_times = [
        {"char": char, "start": index * 0.1, "end": (index + 1) * 0.1}
        for index, char in enumerate(text)
    ]
    cues = tts._group_chars_into_cues(char_times, max_chars=8)
    joined = "".join(item["text"] for item in cues)
    assert joined == text
    assert not any(cue["text"].endswith("小") for cue in cues[:-1])
    assert not any(cue["text"].endswith("碎") for cue in cues[:-1])
    assert not any(
        left["text"].endswith("能") and right["text"].startswith("玩")
        for left, right in pairwise(cues)
    )
    assert not any(cue["text"] in "，。！？；：、,.!?;:" for cue in cues)


def test_all_preschool_caption_cues_align_to_real_asr_including_final_question(
    tmp_path: Path,
) -> None:
    """Independently rerun CPU ASR over every beat WAV, including the final question."""
    from hevi.layer4_legacy.handdraw.asr import transcribe_words

    storyboard = select_kids_storyboard("小狐狸学会轮流")
    beats = [beat for page in storyboard["pages"] for beat in page["beats"]]
    audio_dir = tmp_path / "full-story-audio"
    audio_dir.mkdir()
    _master, alignment_path, duration = tts.build_narration_master(
        [{"id": f"b{index:02d}", "text": beat["text"]} for index, beat in enumerate(beats)],
        audio_dir,
        prefer_cosy=False,
        use_asr=True,
    )
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    assert len(alignment["beats"]) == 8
    assert abs(float(alignment["total_duration"]) - duration) <= 1 / tts.SAMPLE_RATE
    assert float(alignment["characters_per_second"]) <= 3.5

    errors = []
    final_question_errors = []
    for index, beat in enumerate(alignment["beats"]):
        wav = audio_dir / "_synth" / f"{index:04d}.wav"
        assert wav.is_file() and wav.stat().st_size > 1000
        independently_transcribed = transcribe_words(wav)
        assert independently_transcribed, f"CPU ASR returned no words for beat {index}"
        char_times = tts._align_chars_to_words(beat["text"], independently_transcribed)
        assert char_times and "".join(cue["text"] for cue in beat["caption_cues"]) == beat["text"]
        offset = 0
        for cue in beat["caption_cues"]:
            expected_start = min(float(item["start"]) for item in char_times[offset:offset + len(cue["text"])])
            error = abs(float(cue["start"]) - expected_start)
            errors.append(error)
            if beat["text"].startswith("下次你想和谁一起玩球呢？") and cue["text"].startswith("下次"):
                final_question_errors.append(error)
            offset += len(cue["text"])
        assert offset == len(beat["text"])

    assert errors
    p95 = float(np.percentile(errors, 95))
    assert p95 <= 0.25, {"cue_count": len(errors), "p95_seconds": p95, "max_seconds": max(errors)}
    assert len(final_question_errors) == 1
    assert final_question_errors[0] <= 0.25, final_question_errors
