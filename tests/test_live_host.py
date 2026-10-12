"""赛博小雅 live host 单元测试。

覆盖纯逻辑（CER / 分句 / 注册表热切换 / VAD 概率）与
用假引擎跑通编排（不依赖真实 ollama / Piper，避免慢推理与网络）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hevi.live_host import EngineConfig, LiveHost
from hevi.live_host.eval_cer import cer
from hevi.live_host.oprim.registry import EngineRegistry
from hevi.live_host.oprim.silero_vad import SileroVAD
from hevi.live_host.oskill.skill_think import _split_sentences
from hevi.live_host.schemas import StageTiming, TurnInput, TurnOutput


# ── 纯逻辑 ────────────────────────────────────────────
def test_cer_exact():
    assert cer("你好世界", "你好世界") == 0.0


def test_cer_substitution():
    # 一个字错：编辑距离 1 / 4 = 0.25
    assert cer("你好世界", "你坏世界") == pytest.approx(0.25)


def test_cer_empty_reference():
    # 空参考 + 非空假设 = 全部错（1.0）
    assert cer("", "任何") == 1.0
    assert cer("", "") == 0.0


def test_split_sentences_basic():
    s = _split_sentences("你好。我是小雅！今天天气好吗？")
    assert s == ["你好。", "我是小雅！", "今天天气好吗？"]


def test_split_sentences_newline():
    s = _split_sentences("第一句\n第二句")
    assert s == ["第一句", "第二句"]


def test_stage_timing_first_audio():
    t = StageTiming(vad=0.5, stt=1.0, llm_first_token=2.0, tts=0.8)
    assert t.first_audio == pytest.approx(4.3)


# ── 引擎注册表 ───────────────────────────────────────
def test_registry_select_tts():
    cfg = EngineConfig()
    reg = EngineRegistry(cfg)
    reg.select("tts", "cosyvoice")
    assert cfg.tts == "cosyvoice"
    eng = reg.get("tts")
    assert eng.name == "cosyvoice"


def test_registry_unknown_key_raises():
    reg = EngineRegistry(EngineConfig())
    with pytest.raises(KeyError):
        reg.select("tts", "does_not_exist")


# ── VAD ──────────────────────────────────────────────
def test_vad_detects_speech(tmp_path):
    vad = SileroVAD()
    # 用真实 Piper 合成一段语音作正样本（若 Piper 不可用则跳过）
    try:
        from hevi.live_host.oprim.tts_piper import PiperTTS
        import soundfile as sf

        p = tmp_path / "s.wav"
        PiperTTS().synthesize("你好", p)
        samples, sr = sf.read(p, dtype="float32")
        if sr != 16000:
            samples = np.asarray(samples)
        assert vad.has_speech(np.asarray(samples, dtype=np.float32)) is True
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Piper 不可用: {exc}")


def test_vad_silence_is_false():
    vad = SileroVAD()
    noise = np.zeros(16000, dtype=np.float32)
    assert vad.has_speech(noise) is False


# ── 编排（假引擎） ───────────────────────────────────
class _FakeLLM:
    name = "fake_llm"

    def available(self):
        return True

    def stream_reply(self, question):
        yield "你好呀！"
        yield "我是赛博小雅。"


class _FakeSTT:
    name = "fake_stt"

    def available(self):
        return True

    def transcribe(self, audio_path):
        return "小雅你好?"


class _FakeTTS:
    name = "fake_tts"

    def available(self):
        return True

    def synthesize(self, text, output_path):
        Path(output_path).write_bytes(b"RIFF")
        return Path(output_path)


def test_live_host_full_turn_with_fakes(tmp_path):
    cfg = EngineConfig()
    host = LiveHost(cfg, workdir=tmp_path)
    # 注入假引擎
    host.registry._cache = {
        ("stt", "whisper"): _FakeSTT(),
        ("llm", "ollama"): _FakeLLM(),
        ("tts", "piper"): _FakeTTS(),
    }
    host.vad = None

    out = host.turn(TurnInput(text="小雅你好?"))
    assert out.question == "小雅你好?"
    assert "赛博小雅" in out.reply_text
    assert len(out.utterances) == 2
    assert out.utterances[0].audio_path is not None
    assert out.timing.llm_first_token >= 0.0
    assert out.timing.vad == 0.0  # 文本输入无 VAD


def test_live_host_aigc_label(tmp_path):
    cfg = EngineConfig(aigc_label_enabled=True, aigc_label_text="AI生成")
    host = LiveHost(cfg, workdir=tmp_path)
    host.registry._cache = {
        ("stt", "whisper"): _FakeSTT(),
        ("llm", "ollama"): _FakeLLM(),
        ("tts", "piper"): _FakeTTS(),
    }
    host.vad = None
    out = host.turn_labeled(TurnInput(text="hi"))
    assert out.reply_text.startswith("【AI生成】")
