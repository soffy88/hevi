"""hevi.assembly.native_dialogue 测试 — 纯函数直接测,I/O 函数用 lavfi 合成音轨 +
显式注入的 transcribe_fn(不碰真实 faster-whisper 模型,同 segment_qc.py 的 tts_fn 约定)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.native_dialogue import (
    CharacterVoiceRegistry,
    DialogueSourceDecision,
    DuplicateDialogueError,
    assert_no_duplicate_dialogue_renders,
    decide_dialogue_source,
    extract_native_dialogue_audio,
    pinyin_error_rate,
    probe_native_dialogue,
    strip_dialogue_from_track,
    verify_no_duplicate_dialogue_renders,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")


def _make_tone(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(path)],
        check=True,
        capture_output=True,
    )


def _duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


class _FakeCue:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start, self.end, self.text = start, end, text


def test_pinyin_error_rate_ignores_homophone_asr_confusion() -> None:
    # "许兄"被 ASR 听成"徐兄"是真实撞见过的同音字混淆,拼音一样,不该算错。
    assert pinyin_error_rate("许兄这半年清扬相待", "徐兄这半年清洋相待") == 0.0


def test_pinyin_error_rate_catches_real_mispronunciation() -> None:
    # "业满"→"夜晚"拼音本身不同(mǎn vs wǎn),是真实发音级错误。
    rate = pinyin_error_rate("业满", "夜晚")
    assert rate > 0.0


def test_pinyin_error_rate_strips_stage_directions_from_ref() -> None:
    # 2026-07-20 G-FINAL 真机撞见:dialogue.text 里混进了舞台指示"（酒气混着水腥味，
    # 字字缓而沉）",provider 没有念出来(ASR 转写也没有),留在 ref 里会把 PER 算爆
    # (36.4%),但这段其实发音基本准。
    ref = "（酒气混着水腥味，字字缓而沉）实话告你：我本是鬼。"
    hyp = "石花告你,我本是鬼。"  # 同音字混淆(实话↔石花),不是真错误
    assert pinyin_error_rate(ref, hyp) == 0.0


def test_pinyin_error_rate_empty_ref_is_zero() -> None:
    assert pinyin_error_rate("", "随便什么") == 0.0


def test_decide_dialogue_source_no_dialogue_expected() -> None:
    d = decide_dialogue_source(
        segment_id="s1", expected_text="", hyp_text="", native_windows_s=[], voice_sim=None
    )
    assert d.source == "none"


def test_decide_dialogue_source_no_native_speech_detected() -> None:
    d = decide_dialogue_source(
        segment_id="s1",
        expected_text="别？从何说起？",
        hyp_text="",
        native_windows_s=[],
        voice_sim=None,
    )
    assert d.source == "fallback"
    assert "没测到" in d.reason


def test_decide_dialogue_source_mispronounced_falls_back() -> None:
    d = decide_dialogue_source(
        segment_id="s1",
        expected_text="今天天气很好",
        hyp_text="明天心情很差",
        native_windows_s=[(0.0, 2.0)],
        voice_sim=None,
    )
    assert d.source == "fallback"
    assert "发音错误率" in d.reason


def test_decide_dialogue_source_voice_mismatch_falls_back() -> None:
    d = decide_dialogue_source(
        segment_id="s2",
        expected_text="别？从何说起？",
        hyp_text="别？从何说起？",
        native_windows_s=[(0.0, 2.0)],
        voice_sim=0.4,
    )
    assert d.source == "fallback"
    assert "音色相似度" in d.reason


def test_decide_dialogue_source_first_utterance_has_no_voice_ref_yet() -> None:
    # voice_sim=None(角色第一次开口,还没攒出参考)不能被当成"不通过"错杀。
    d = decide_dialogue_source(
        segment_id="s1",
        expected_text="别？从何说起？",
        hyp_text="别？从何说起？",
        native_windows_s=[(0.0, 2.0)],
        voice_sim=None,
    )
    assert d.source == "native"


def test_decide_dialogue_source_all_checks_pass_is_native() -> None:
    d = decide_dialogue_source(
        segment_id="s1",
        expected_text="别？从何说起？",
        hyp_text="别？从何说起？",
        native_windows_s=[(1.0, 3.0)],
        voice_sim=0.9,
    )
    assert d == DialogueSourceDecision(
        segment_id="s1",
        source="native",
        reason="",
        native_windows_s=((1.0, 3.0),),
        per=0.0,
        voice_sim=0.9,
    )


def test_character_voice_registry_no_reference_yet_returns_none() -> None:
    reg = CharacterVoiceRegistry()
    assert reg.similarity("王六郎", [1.0, 0.0]) is None


def test_character_voice_registry_similarity_after_register() -> None:
    reg = CharacterVoiceRegistry()
    reg.register("王六郎", [1.0, 0.0])
    assert reg.similarity("王六郎", [1.0, 0.0]) == pytest.approx(1.0)
    assert reg.similarity("王六郎", [0.0, 1.0]) == pytest.approx(0.0)


@ffmpeg_only
async def test_probe_native_dialogue_uses_injected_transcribe_fn(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_tone(clip, 2.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        assert path.exists()
        return [_FakeCue(0.5, 1.5, "测试台词")]

    windows, text = await probe_native_dialogue(
        clip, tmp_wav=tmp_path / "probe.wav", transcribe_fn=fake_transcribe
    )
    assert windows == [(0.5, 1.5)]
    assert text == "测试台词"


@ffmpeg_only
async def test_probe_native_dialogue_empty_when_no_speech(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_tone(clip, 1.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        return []

    windows, text = await probe_native_dialogue(
        clip, tmp_wav=tmp_path / "probe.wav", transcribe_fn=fake_transcribe
    )
    assert windows == []
    assert text == ""


@ffmpeg_only
async def test_extract_native_dialogue_audio_spans_all_windows(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_tone(clip, 5.0)
    out = tmp_path / "dialogue.wav"

    await extract_native_dialogue_audio(clip, [(1.0, 2.0), (3.0, 3.5)], output_path=out)

    # span = [1.0-0.15, 3.5+0.15] = [0.85, 3.65] = 2.8s(含两端 padding,覆盖两个窗口
    # 之间的自然停顿,不是掐头去尾拼接)
    assert _duration(out) == pytest.approx(2.8, abs=0.1)


@ffmpeg_only
async def test_strip_dialogue_from_track_no_windows_copies_through(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_tone(clip, 2.0)
    out = tmp_path / "ambient.wav"

    await strip_dialogue_from_track(clip, [], output_path=out)

    assert out.exists()
    assert _duration(out) == pytest.approx(2.0, abs=0.1)


@ffmpeg_only
async def test_strip_dialogue_from_track_ducks_speech_window(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_tone(clip, 3.0)
    out = tmp_path / "ambient.wav"

    await strip_dialogue_from_track(clip, [(1.0, 2.0)], output_path=out, floor_db=-90.0)

    # 静音窗口(0.85-2.15s,含 padding)中点应该被压到接近零;窗口外(比如 0.3s)不受影响。
    def _mean_abs_amplitude(at: float) -> float:
        import wave

        raw = tmp_path / f"_probe_{at}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out), "-ss", str(at), "-t", "0.2", str(raw)],
            check=True,
            capture_output=True,
        )
        with wave.open(str(raw), "rb") as w:
            frames = w.readframes(w.getnframes())
        if not frames:
            return 0.0
        import array

        samples = array.array("h", frames)
        return sum(abs(s) for s in samples) / len(samples)

    assert _mean_abs_amplitude(1.5) < _mean_abs_amplitude(0.3) / 10


def test_merge_asr_cues_joins_close_fragments() -> None:
    from hevi.assembly.native_dialogue import _merge_asr_cues

    cues = [_FakeCue(0.0, 1.0, "许兄这半年"), _FakeCue(1.5, 3.0, "清扬相待")]
    spans = _merge_asr_cues(cues, merge_gap_s=2.0)
    assert spans == [(0.0, 3.0, "许兄这半年清扬相待")]


def test_merge_asr_cues_keeps_far_apart_fragments_separate() -> None:
    from hevi.assembly.native_dialogue import _merge_asr_cues

    cues = [_FakeCue(0.0, 1.0, "别从何说起"), _FakeCue(30.0, 31.0, "别从何说起")]
    spans = _merge_asr_cues(cues, merge_gap_s=2.0)
    assert spans == [(0.0, 1.0, "别从何说起"), (30.0, 31.0, "别从何说起")]


@ffmpeg_only
async def test_verify_no_duplicate_dialogue_renders_flags_real_duplicate(tmp_path: Path) -> None:
    clip = tmp_path / "final.mp4"
    _make_tone(clip, 40.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        return [_FakeCue(2.0, 4.0, "别你这话从何说起"), _FakeCue(30.0, 32.0, "别你这话从何说起")]

    violations = await verify_no_duplicate_dialogue_renders(
        clip,
        expected_lines=[("许渔夫", "别你这话从何说起")],
        tmp_wav=tmp_path / "probe.wav",
        transcribe_fn=fake_transcribe,
    )

    assert len(violations) == 1
    assert violations[0].speaker == "许渔夫"
    assert violations[0].windows_s == ((2.0, 4.0), (30.0, 32.0))


@ffmpeg_only
async def test_verify_no_duplicate_dialogue_renders_flags_close_together_duplicate(
    tmp_path: Path,
) -> None:
    # 2026-07-20 G-FINAL v1 真机撞见的实际形态:原声 + 独立 TTS 两条渲染的开口时点只差
    # 0.9-1.0s,小于合并间隔——如果先无脑按 merge_gap_s 全局合并再比对,这种"挨得很近的
    # 两次独立渲染"会被误并成一段,检测不出来。两个 cue 各自都已经是这句台词的完整渲染,
    # 不该因为离得近就被合并放过。
    clip = tmp_path / "final.mp4"
    _make_tone(clip, 10.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        return [
            _FakeCue(2.0, 6.0, "别你这话从何说起"),
            _FakeCue(2.9, 4.0, "别你这话从何说起"),
        ]

    violations = await verify_no_duplicate_dialogue_renders(
        clip,
        expected_lines=[("许渔夫", "别你这话从何说起")],
        tmp_wav=tmp_path / "probe.wav",
        transcribe_fn=fake_transcribe,
    )

    assert len(violations) == 1
    assert violations[0].windows_s == ((2.0, 6.0), (2.9, 4.0))


@ffmpeg_only
async def test_verify_no_duplicate_dialogue_renders_single_occurrence_is_clean(
    tmp_path: Path,
) -> None:
    clip = tmp_path / "final.mp4"
    _make_tone(clip, 10.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        return [_FakeCue(2.0, 4.0, "别你这话从何说起")]

    violations = await verify_no_duplicate_dialogue_renders(
        clip,
        expected_lines=[("许渔夫", "别你这话从何说起")],
        tmp_wav=tmp_path / "probe.wav",
        transcribe_fn=fake_transcribe,
    )

    assert violations == []


@ffmpeg_only
async def test_verify_no_duplicate_dialogue_renders_merges_same_utterance_pause(
    tmp_path: Path,
) -> None:
    # 同一句台词中间有个自然停顿被 ASR 切成两段 cue——不该被误判成渲染了两次。
    clip = tmp_path / "final.mp4"
    _make_tone(clip, 10.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        return [_FakeCue(2.0, 3.0, "别你这话"), _FakeCue(3.5, 4.5, "从何说起")]

    violations = await verify_no_duplicate_dialogue_renders(
        clip,
        expected_lines=[("许渔夫", "别你这话从何说起")],
        tmp_wav=tmp_path / "probe.wav",
        transcribe_fn=fake_transcribe,
    )

    assert violations == []


@ffmpeg_only
async def test_assert_no_duplicate_dialogue_renders_raises_on_violation(tmp_path: Path) -> None:
    clip = tmp_path / "final.mp4"
    _make_tone(clip, 40.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        return [_FakeCue(2.0, 4.0, "别你这话从何说起"), _FakeCue(30.0, 32.0, "别你这话从何说起")]

    with pytest.raises(DuplicateDialogueError):
        await assert_no_duplicate_dialogue_renders(
            clip,
            expected_lines=[("许渔夫", "别你这话从何说起")],
            tmp_wav=tmp_path / "probe.wav",
            transcribe_fn=fake_transcribe,
        )


@ffmpeg_only
async def test_assert_no_duplicate_dialogue_renders_passes_when_clean(tmp_path: Path) -> None:
    clip = tmp_path / "final.mp4"
    _make_tone(clip, 10.0)

    def fake_transcribe(path: Path, *, language: str | None = None) -> list[_FakeCue]:
        return [_FakeCue(2.0, 4.0, "别你这话从何说起")]

    await assert_no_duplicate_dialogue_renders(
        clip,
        expected_lines=[("许渔夫", "别你这话从何说起")],
        tmp_wav=tmp_path / "probe.wav",
        transcribe_fn=fake_transcribe,
    )
