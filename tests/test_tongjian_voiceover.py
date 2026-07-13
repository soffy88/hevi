"""L3 配音 + G3 校验门测试。"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hevi.tongjian.schemas import (
    Act,
    AudioSegment,
    Constitution,
    GateResult,
    Script,
    ScriptLine,
    Timeline,
    TimelineGap,
    VisualStyle,
)
from hevi.tongjian.voiceover import (
    _char_error_rate,
    _short_hash,
    build_voiceover,
    gate_voiceover,
    synthesize_voiceover,
)


# ── fixtures ──────────────────────────────────────────────────────────────


def _make_script(lines: list[dict] | None = None) -> Script:
    if lines is None:
        lines = [
            {
                "line_id": "LN001",
                "act": 1,
                "type": "narration",
                "speaker": "NARRATOR",
                "text": "智伯设宴,韩魏赵三家大夫皆列席。",
            },
            {
                "line_id": "LN002",
                "act": 1,
                "type": "dialogue",
                "speaker": "C001",
                "text": "祸乱要来,也得我来挑起。",
            },
            {
                "line_id": "LN003",
                "act": 2,
                "type": "narration",
                "speaker": "NARRATOR",
                "text": "赵襄子拒绝割地,智伯怒而兴兵。",
            },
        ]
    return Script(lines=[ScriptLine(**ln) for ln in lines])


def _make_constitution(target_duration_sec: int = 180) -> Constitution:
    return Constitution(
        thesis="礼崩乐坏",
        narrative_stance="上帝视角旁白",
        tone=["肃杀"],
        act_structure=[
            Act(act=1, title="索地", events=["E001"], emotion_curve="压抑"),
            Act(act=2, title="围城", events=["E002"], emotion_curve="紧张"),
        ],
        target_duration_sec=target_duration_sec,
    )


def _write_fake_wav(path: Path, duration_ms: int = 2000) -> None:
    """写一个最小合法 WAV 文件(16kHz mono 16bit),时长约 duration_ms。"""
    sample_rate = 16000
    num_samples = int(sample_rate * duration_ms / 1000)
    data_size = num_samples * 2  # 16bit = 2 bytes per sample
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        # RIFF header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # chunk size
        f.write(struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16))
        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)


def _mock_tts_fn(duration_ms: int = 2000):
    """返回一个 mock TTS 函数,合成时写假 WAV 文件。"""

    async def _tts(*, script, output_path, **kwargs):
        _write_fake_wav(output_path, duration_ms)
        return output_path

    return _tts


# ── CER 计算测试 ──────────────────────────────────────────────────────────


class TestCharErrorRate:
    def test_identical(self):
        assert _char_error_rate("你好世界", "你好世界") == 0.0

    def test_empty_reference(self):
        assert _char_error_rate("", "任何内容") == 0.0

    def test_one_error(self):
        cer = _char_error_rate("你好世界", "你好时界")
        assert 0.2 <= cer <= 0.3  # 1/4 = 0.25

    def test_completely_different(self):
        cer = _char_error_rate("你好", "世界末日")
        assert cer >= 0.5

    def test_whitespace_ignored(self):
        assert _char_error_rate("你 好 世 界", "你好世界") == 0.0


# ── schema 测试 ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_audio_segment_defaults(self):
        seg = AudioSegment(line_id="LN001")
        assert seg.duration_ms == 0
        assert seg.file == ""

    def test_timeline_gap_defaults(self):
        gap = TimelineGap(after_line="LN001")
        assert gap.duration_ms == 1500
        assert gap.purpose == "act_transition"

    def test_timeline_empty(self):
        tl = Timeline()
        assert tl.audio_segments == []
        assert tl.total_duration_ms == 0


# ── synthesize_voiceover 测试 ─────────────────────────────────────────────


class TestSynthesizeVoiceover:
    @pytest.mark.asyncio
    async def test_basic_synthesis(self, tmp_path):
        script = _make_script()
        tts_fn = _mock_tts_fn(duration_ms=2000)
        mock_dur = AsyncMock(return_value=2000)

        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            timeline = await synthesize_voiceover(
                script,
                output_dir=tmp_path,
                tts_fn=tts_fn,
            )

        assert len(timeline.audio_segments) == 3
        assert timeline.audio_segments[0].line_id == "LN001"
        assert timeline.audio_segments[0].duration_ms == 2000
        assert timeline.audio_segments[0].t_start_ms == 0
        assert timeline.audio_segments[0].t_end_ms == 2000

    @pytest.mark.asyncio
    async def test_voice_by_speaker_resolves_per_dialogue_line(self, tmp_path):
        """2026-07-13 治"多角色对话只有一个默认声音":dialogue 行按 speaker 查
        voice_by_speaker 拿到专属音色,旁白行(NARRATOR)不受这张表影响,恒传 None
        (P0 单声线退化行为不变)。"""
        script = _make_script()  # LN001=narration/NARRATOR, LN002=dialogue/C001, LN003=narration
        seen_voices: list[tuple[str, str | None]] = []

        async def _tts(*, script, output_path, voice=None, **kwargs):
            seen_voices.append((script[0].speaker_id, voice))
            _write_fake_wav(output_path, 1000)
            return output_path

        mock_dur = AsyncMock(return_value=1000)
        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            await synthesize_voiceover(
                script,
                output_dir=tmp_path,
                tts_fn=_tts,
                voice_by_speaker={"C001": "zh_male_deep"},
            )

        by_speaker = dict(seen_voices)
        assert by_speaker["C001"] == "zh_male_deep"
        assert by_speaker["NARRATOR"] is None

    @pytest.mark.asyncio
    async def test_emotion_passed_through_for_all_line_types(self, tmp_path):
        """2026-07-13 治"ScriptLine.emotion 填了但 TTS 从不读":每行(旁白/对白都算,
        不限 dialogue)原样把 emotion 传给 tts_fn;空字符串传 None,不是空字符串本身。"""
        script = _make_script(
            [
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "智伯设宴。",
                    "emotion": "倨傲",
                },
                {
                    "line_id": "LN002",
                    "act": 1,
                    "type": "dialogue",
                    "speaker": "C001",
                    "text": "祸乱要来。",
                    "emotion": "",
                },
            ]
        )
        seen_emotions: list[tuple[str, str | None]] = []

        async def _tts(*, script, output_path, voice=None, emotion=None, **kwargs):
            seen_emotions.append((script[0].speaker_id, emotion))
            _write_fake_wav(output_path, 1000)
            return output_path

        mock_dur = AsyncMock(return_value=1000)
        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            await synthesize_voiceover(script, output_dir=tmp_path, tts_fn=_tts)

        by_speaker = dict(seen_emotions)
        assert by_speaker["NARRATOR"] == "倨傲"
        assert by_speaker["C001"] is None

    @pytest.mark.asyncio
    async def test_act_transition_gap(self, tmp_path):
        """幕间切换时应自动插入 1.5s 空隙。"""
        script = _make_script()  # LN001=act1, LN002=act1, LN003=act2
        mock_dur = AsyncMock(return_value=1000)

        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            timeline = await synthesize_voiceover(
                script,
                output_dir=tmp_path,
                tts_fn=_mock_tts_fn(1000),
            )

        assert len(timeline.gaps) == 1
        assert timeline.gaps[0].purpose == "act_transition"
        assert timeline.gaps[0].duration_ms == 1500

        # LN003 的 t_start 应该是 1000+1000+1500=3500
        ln3 = [s for s in timeline.audio_segments if s.line_id == "LN003"][0]
        assert ln3.t_start_ms == 3500

    @pytest.mark.asyncio
    async def test_empty_text_skipped(self, tmp_path):
        """空文本行应跳过不合成。"""
        script = _make_script(
            [
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "有内容的行",
                },
                {
                    "line_id": "LN002",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "",
                },
            ]
        )
        mock_dur = AsyncMock(return_value=1000)
        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            timeline = await synthesize_voiceover(
                script,
                output_dir=tmp_path,
                tts_fn=_mock_tts_fn(1000),
            )
        assert len(timeline.audio_segments) == 1

    @pytest.mark.asyncio
    async def test_tts_failure_graceful(self, tmp_path):
        """TTS 合成失败不应崩溃,跳过该行。"""

        async def _failing_tts(*, script, output_path, **kwargs):
            raise RuntimeError("GPU OOM")

        script = _make_script(
            [
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "正常行",
                },
            ]
        )
        timeline = await synthesize_voiceover(
            script,
            output_dir=tmp_path,
            tts_fn=_failing_tts,
        )
        assert len(timeline.audio_segments) == 0

    @pytest.mark.asyncio
    async def test_total_duration_accumulates(self, tmp_path):
        """total_duration_ms 应等于所有片段时长 + 空隙之和。"""
        script = _make_script()
        mock_dur = AsyncMock(return_value=1000)
        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            timeline = await synthesize_voiceover(
                script,
                output_dir=tmp_path,
                tts_fn=_mock_tts_fn(1000),
            )
        # 3 segments × 1000ms + 1 gap × 1500ms = 4500ms
        assert timeline.total_duration_ms == 4500

    @pytest.mark.asyncio
    async def test_filenames_follow_spec(self, tmp_path):
        """文件名应为 audio/ln001_XXXX.wav 格式。"""
        script = _make_script(
            [
                {
                    "line_id": "LN001",
                    "act": 1,
                    "type": "narration",
                    "speaker": "NARRATOR",
                    "text": "测试",
                },
            ]
        )
        mock_dur = AsyncMock(return_value=1000)
        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            timeline = await synthesize_voiceover(
                script,
                output_dir=tmp_path,
                tts_fn=_mock_tts_fn(1000),
            )
        assert timeline.audio_segments[0].file.startswith("audio/ln001_")
        assert timeline.audio_segments[0].file.endswith(".wav")


# ── gate_voiceover 测试 ───────────────────────────────────────────────────


class TestGateVoiceover:
    @pytest.mark.asyncio
    async def test_empty_timeline_fails(self):
        timeline = Timeline()
        script = _make_script()
        constitution = _make_constitution()
        result = await gate_voiceover(timeline, script, constitution)
        assert not result.passed
        assert any("没有任何音频片段" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_good_timeline_passes(self):
        """无音频文件时(纯 schema 校验),只做基本完整性检查。"""
        timeline = Timeline(
            audio_segments=[
                AudioSegment(
                    line_id="LN001",
                    file="audio/ln001.wav",
                    duration_ms=60000,
                    t_start_ms=0,
                    t_end_ms=60000,
                ),
                AudioSegment(
                    line_id="LN002",
                    file="audio/ln002.wav",
                    duration_ms=60000,
                    t_start_ms=60000,
                    t_end_ms=120000,
                ),
                AudioSegment(
                    line_id="LN003",
                    file="audio/ln003.wav",
                    duration_ms=60000,
                    t_start_ms=120000,
                    t_end_ms=180000,
                ),
            ],
            total_duration_ms=180000,
        )
        script = _make_script()
        constitution = _make_constitution(target_duration_sec=180)
        result = await gate_voiceover(timeline, script, constitution)
        assert result.passed

    @pytest.mark.asyncio
    async def test_duration_deviation_warning(self):
        """时长偏差 > 20% 应产生 warning(非 error)。"""
        timeline = Timeline(
            audio_segments=[
                AudioSegment(
                    line_id="LN001",
                    file="audio/ln001.wav",
                    duration_ms=50000,
                    t_start_ms=0,
                    t_end_ms=50000,
                ),
            ],
            total_duration_ms=50000,
        )
        script = _make_script()
        constitution = _make_constitution(target_duration_sec=180)
        result = await gate_voiceover(timeline, script, constitution)
        assert result.passed  # warning, not error
        assert any("偏差" in w for w in result.warnings)


# ── build_voiceover 集成测试 ──────────────────────────────────────────────


class TestBuildVoiceover:
    @pytest.mark.asyncio
    async def test_end_to_end(self, tmp_path):
        script = _make_script()
        constitution = _make_constitution(target_duration_sec=10)
        mock_dur = AsyncMock(return_value=2500)

        with patch("hevi.tongjian.voiceover._get_audio_duration_ms", mock_dur):
            timeline, result = await build_voiceover(
                script,
                constitution,
                output_dir=tmp_path,
                tts_fn=_mock_tts_fn(2500),
            )

        assert len(timeline.audio_segments) == 3
        assert timeline.total_duration_ms > 0
        # G3 检查应通过(无 ASR 验证时默认通过)
        assert isinstance(result, GateResult)


# ── 短 hash 测试 ──────────────────────────────────────────────────────────


class TestShortHash:
    def test_deterministic(self):
        assert _short_hash("hello") == _short_hash("hello")

    def test_length(self):
        assert len(_short_hash("test")) == 4

    def test_different_inputs(self):
        assert _short_hash("abc") != _short_hash("def")
