"""Voice-Pro 配音内核 3O:五原语 / 五技能 / 三件套 workflow / 接线。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hevi.assembly.subtitle_align import Cue
from hevi.audio.cosyvoice_service import cosyvoice_synthesize
from hevi.audio.f5_tts_service import f5_tts_synthesize
from hevi.dub.translate import dub_video, translate_cues
from hevi.production.voicepro_kernel_workflow import (
    VoiceProKernelConfig,
    VoiceProKernelInput,
    voicepro_kernel_workflow,
)
from hevi.voicepro.omodul.dub_plan import plan_dub_artifacts
from hevi.voicepro.oprim.cosy_mode import (
    CV3_SYSTEM_PROMPT,
    apply_cv3_prefix,
    cv3_fields_for_mode,
    resolve_inference_mode,
)
from hevi.voicepro.oprim.cue_clock import (
    complete_sentence,
    is_complete_sentence,
    merge_sentence_fragments,
    split_into_sentences,
)
from hevi.voicepro.oprim.f5_catalog import list_models, parse_conversation, pick_model_for_language
from hevi.voicepro.oprim.mix_levels import choose_strategy, ffmpeg_remix_args, plan_mix
from hevi.voicepro.oprim.timeline_pad import (
    leading_silence_ms,
    place_clips_on_clock,
    total_timeline_ms,
)
from hevi.voicepro.oprim.translate_backoff import (
    merge_batch_and_retries,
    retry_delays,
    should_keep_original,
)
from hevi.voicepro.oskill.cosy_payload import build_cosy_line
from hevi.voicepro.oskill.f5_speakers import SpeakerRef, resolve_turns
from hevi.voicepro.oskill.subtitle_timeline import merge_and_split_cues, plan_timeline
from hevi.voicepro.oskill.translate_retry import fill_missing_lines
from hevi.voicepro.oskill.vocal_remix import plan_vocal_remix, stem_split_command
from hevi.voicepro.schemas import TimedCue


def test_three_o_directory_structure_exists() -> None:
    root = Path(__file__).parents[1] / "hevi" / "voicepro"
    for sub in ("oprim", "oskill", "omodul", "data"):
        assert (root / sub).is_dir(), f"缺少 3O 目录: {sub}"
    assert (root / "schemas.py").is_file()
    assert (root / "data" / "f5_models.json").is_file()


def test_oprim_does_not_import_oskill_or_omodul() -> None:
    root = Path(__file__).parents[1] / "hevi" / "voicepro" / "oprim"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import", "from")) and (
                "voicepro.oskill" in stripped or "voicepro.omodul" in stripped
            ):
                raise AssertionError(f"{path.name} 越权引用: {stripped}")


def test_oskill_does_not_import_omodul() -> None:
    root = Path(__file__).parents[1] / "hevi" / "voicepro" / "oskill"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import", "from")) and "voicepro.omodul" in stripped:
                raise AssertionError(f"{path.name} 越权引用: {stripped}")


def test_merge_and_split_joins_incomplete_then_splits() -> None:
    cues = [
        TimedCue(start=0.0, end=1.2, text="Hello there"),
        TimedCue(start=1.3, end=2.5, text="we should go now."),
        TimedCue(start=5.0, end=6.5, text="Later."),
    ]
    out = merge_and_split_cues(cues, lang="en")
    assert len(out) == 2
    assert "Hello there" in out[0].text
    assert out[0].end <= out[1].start + 1e-6
    assert out[1].text.startswith("Later")


def test_sentence_helpers() -> None:
    assert split_into_sentences("Hi. Bye.") == ["Hi.", "Bye."]
    assert not is_complete_sentence("who")
    assert complete_sentence("who is there") == "who is there?"
    assert merge_sentence_fragments(["Hello", "there."]) == ["Hello there."]


def test_timeline_pads_and_overflow() -> None:
    slots = place_clips_on_clock([0.5, 2.0], [0.4, 1.5])
    assert leading_silence_ms(slots) == 500
    assert slots[0].pad_after_ms == 1100
    assert not slots[0].overflowed
    long = place_clips_on_clock([0.0, 1.0], [1.5, 0.4])
    assert long[1].overflowed
    assert total_timeline_ms(long) == 1900


def test_plan_timeline_uses_merged_starts() -> None:
    cues = [TimedCue(start=0.2, end=1.0, text="A."), TimedCue(start=1.5, end=2.0, text="B.")]
    slots = plan_timeline(cues, [0.3, 0.2])
    assert slots[0].start_ms == 200
    assert slots[0].pad_after_ms == 1000


def test_mix_replace_vs_remix() -> None:
    assert choose_strategy(has_bed=False) == "replace"
    plan = plan_mix(has_bed=True, bed_from_video=False)
    assert plan.strategy == "remix"
    assert "amix" in plan.filter_complex
    args = ffmpeg_remix_args(video="v.mp4", audio="a.wav", output="o.mp4")
    assert "-filter_complex" in args
    assert "[0:a]" in args[args.index("-filter_complex") + 1]


def test_vocal_remix_and_demucs_args() -> None:
    plan = plan_vocal_remix(keep_bed=True, bed_from_video=True)
    assert plan.strategy == "remix"
    cmd = stem_split_command("in.wav", "out")
    assert cmd[:3] == ["-m", "demucs.separate", "-n"]
    assert "--two-stems=vocals" in cmd


def test_cosy_modes_and_cv3_prefix() -> None:
    assert resolve_inference_mode(ref_text="hi") == "zero_shot"
    assert resolve_inference_mode() == "cross_lingual"
    assert resolve_inference_mode(instruct_text="whisper") == "instruct"
    assert resolve_inference_mode(requested="Cross-Lingual", ref_text="x") == "cross_lingual"
    prefixed = apply_cv3_prefix("hello", family="cosyvoice3", mode="cross_lingual")
    assert prefixed.startswith(CV3_SYSTEM_PROMPT)
    prompt, tts, instruct = cv3_fields_for_mode(
        family="cosyvoice3",
        mode="zero_shot",
        tts_text="说中文",
        ref_text="参考",
        instruct_text=None,
    )
    assert prompt.startswith(CV3_SYSTEM_PROMPT)
    assert tts == "说中文"
    assert instruct == ""
    line = build_cosy_line(
        text="bonjour",
        voice_ref="/ref.wav",
        requested_mode="instruct",
        model_name="Fun-CosyVoice3-0.5B",
    )
    assert line.inference_mode == "instruct"
    assert CV3_SYSTEM_PROMPT in line.instruct_text


def test_f5_catalog_and_conversation() -> None:
    names = list_models()
    assert "SWivid/F5-TTS_v1" in names
    assert pick_model_for_language("fr").name == "RASPIAUDIO/F5-French"
    assert pick_model_for_language("ja").name == "Jmica/JA_21999120"
    turns = parse_conversation("{spk1} hello\n{spk2} hi there")
    assert [t.speaker for t in turns] == ["spk1", "spk2"]
    bound = resolve_turns(
        "{spk1} a\n{spk2} b",
        language="es",
        speakers={
            "spk1": SpeakerRef("spk1", "a.wav", "aa"),
            "spk2": SpeakerRef("spk2", "b.wav", "bb"),
        },
    )
    assert bound[0].model.name == "jpgallegoar/F5-Spanish"
    assert bound[1].reference_audio == "b.wav"


def test_translate_backoff_keep_original() -> None:
    assert retry_delays() == [2.0, 4.0, 8.0]
    assert should_keep_original(None, "src")
    assert should_keep_original("  ", "src")
    rows = merge_batch_and_retries(["a", "b"], {0: "A"}, {})
    assert rows[0].translated == "A" and not rows[0].kept_original
    assert rows[1].translated == "b" and rows[1].kept_original


@pytest.mark.asyncio
async def test_fill_missing_retries_then_keeps() -> None:
    async def boom(_text: str) -> str:
        raise RuntimeError("rate")

    rows = await fill_missing_lines(["x"], {}, boom, sleep_fn=None, max_retries=2)
    assert rows[0].kept_original
    assert rows[0].translated == "x"

    async def ok(text: str) -> str:
        return text.upper()

    rows = await fill_missing_lines(["hi"], {}, ok, sleep_fn=None)
    assert rows[0].translated == "HI"


@pytest.mark.asyncio
async def test_workflow_writes_report(tmp_path: Path) -> None:
    result = await voicepro_kernel_workflow(
        VoiceProKernelConfig(language="en", keep_bed=True),
        VoiceProKernelInput(
            cues=[{"start": 0.0, "end": 2.0, "text": "Hello world we should go now."}],
            conversation_text="{spk1} hi\n{spk2} there",
            ref_text="ref",
        ),
        tmp_path,
    )
    assert result["status"] == "completed"
    assert Path(result["report_path"]).is_file()
    empty = await voicepro_kernel_workflow(
        VoiceProKernelConfig(),
        VoiceProKernelInput(),
        tmp_path / "empty",
    )
    assert empty["status"] == "failed"


def test_plan_dub_artifacts_fuses_five_kernels() -> None:
    plan = plan_dub_artifacts(
        [{"start": 0.0, "end": 1.5, "text": "Hello there we leave now."}],
        language="fr",
        keep_bed=True,
        inference_mode="zero_shot",
        ref_text="sample",
        conversation_text="{spk1} bonjour",
    )
    assert plan.cues
    assert plan.mix is not None and plan.mix.strategy == "remix"
    assert plan.cosy_mode == "zero_shot"
    assert plan.f5_model == "RASPIAUDIO/F5-French"
    assert plan.speakers[0].speaker == "spk1"


@pytest.mark.asyncio
async def test_translate_cues_retries_missing_line() -> None:
    cues = [Cue(start=0.0, end=1.0, text="甲"), Cue(start=1.0, end=2.0, text="乙")]
    llm = AsyncMock(side_effect=[{"content": '{"0":"A"}'}, {"content": "B"}])
    out = await translate_cues(cues, target_language="en", llm=llm, sleep_fn=None)
    assert [c.text for c in out] == ["A", "B"]
    assert llm.await_count == 2


@pytest.mark.asyncio
async def test_cosyvoice_serializes_inference_mode(tmp_path: Path) -> None:
    fake = AsyncMock()
    fake.post = AsyncMock(return_value=httpx.Response(200, content=b"WAV"))
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    with patch("hevi.audio.cosyvoice_service.httpx.AsyncClient", return_value=fake):
        await cosyvoice_synthesize(
            script=[
                SimpleNamespace(
                    text="hi",
                    inference_mode="instruct",
                    instruct_text="whisper",
                )
            ],
            output_path=tmp_path / "o.wav",
        )
    body = fake.post.await_args.kwargs["json"]
    assert body["script"][0]["inference_mode"] == "instruct"
    assert body["script"][0]["instruct_text"] == "whisper"


@pytest.mark.asyncio
async def test_f5_sends_catalog_model_name(tmp_path: Path) -> None:
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    fake = AsyncMock()
    fake.post = AsyncMock(return_value=httpx.Response(200, content=b"WAV"))
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    with patch("hevi.audio.f5_tts_service.httpx.AsyncClient", return_value=fake):
        await f5_tts_synthesize(
            text="hola",
            output_path=tmp_path / "o.wav",
            reference_audio=ref,
            reference_text="ref",
            language="es",
        )
    data = fake.post.await_args.kwargs["data"]
    assert data["model_name"] == "jpgallegoar/F5-Spanish"


@pytest.mark.asyncio
async def test_dub_video_sentence_merge_keeps_orchestration() -> None:
    cues = [Cue(start=0.0, end=1.0, text="你好世界")]
    calls: dict[str, object] = {}

    def transcribe_fn(_p: Path) -> list[Cue]:
        return cues

    async def synth_fn(*, cues: list[Cue], language: str, output_path: Path) -> Path:
        calls["texts"] = [c.text for c in cues]
        calls["language"] = language
        return output_path

    async def mux_fn(*, video: Path, audio: Path, output: Path) -> Path:
        calls["mux"] = str(output)
        return output

    llm = AsyncMock(return_value={"content": '{"0":"hello world"}'})
    res = await dub_video(
        video_path="in.mp4",
        target_language="en",
        output_path="out_en.mp4",
        llm=llm,
        transcribe_fn=transcribe_fn,
        synth_fn=synth_fn,
        mux_fn=mux_fn,
    )
    assert res["cues"] == 1
    texts = calls["texts"]
    assert isinstance(texts, list)
    assert texts[0].startswith("hello world")
