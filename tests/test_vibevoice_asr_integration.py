"""v9.1 VibeVoice-ASR 借鉴落地: 热词生成 + gen-engine 端点 + speaker 核对。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from hevi.tongjian.hotwords import build_asr_hotwords, hotwords_prompt
from hevi.tongjian.schemas import (
    ChapterIR,
    CharacterIR,
    EventIR,
    LocationHint,
    QuoteIR,
    Script,
    ScriptLine,
)


def _chapter_ir() -> ChapterIR:
    return ChapterIR(
        meta={"source": "资治通鉴·周纪一", "year_range": (0, 0), "char_count": 100},
        characters=[
            CharacterIR(
                character_id="c_zhihu", canonical_name="智伯",
                aliases=["智瑶"], role_in_chapter="antagonist",
            ),
            CharacterIR(
                character_id="c_xiangzi", canonical_name="赵襄子",
                role_in_chapter="protagonist",
            ),
        ],
        events=[
            EventIR(
                event_id="E1", summary="智伯围晋阳而灌之",
                actors=["c_zhihu", "c_xiangzi"], dramatic_weight=5,
            ),
        ],
        quotes=[QuoteIR(quote_id="Q1", speaker="c_zhihu", original="吾欲地于赵", event_id="E1")],
        locations=[LocationHint(scene_hint_id="L1", name="晋阳", events=["E1"])],
    )


def test_build_asr_hotwords_covers_roles_locations() -> None:
    hotwords = build_asr_hotwords(_chapter_ir())
    assert "智伯" in hotwords
    assert "赵襄子" in hotwords
    assert "晋阳" in hotwords
    assert len(hotwords) == len(set(hotwords))  # 去重
    assert hotwords_prompt(hotwords) != ""


def test_hotwords_cap_and_dedup() -> None:
    ir = _chapter_ir()
    assert len(build_asr_hotwords(ir, max_words=2)) <= 2


# ── _asr_speaker_check: 说话人核对 ────────────────────────────────────────


def test_speaker_check_no_overlap_warns() -> None:
    from hevi.tongjian.assemble import _asr_speaker_check

    script = Script(
        lines=[ScriptLine(line_id="LN001", act=1, type="dialogue", speaker="c_zhihu", text="x")]
    )
    note = _asr_speaker_check(
        [{"speaker": "SPEAKER_02", "text": "x"}], script
    )
    assert "无交集" in note


def test_speaker_check_overlap_ok() -> None:
    from hevi.tongjian.assemble import _asr_speaker_check

    script = Script(
        lines=[ScriptLine(line_id="LN001", act=1, type="dialogue", speaker="SPEAKER_01", text="x")]
    )
    assert _asr_speaker_check([{"speaker": "SPEAKER_01", "text": "x"}], script) == ""


# ── _asr_reverify: VibeVoice-ASR 优先, whisper 回退 ───────────────────────


@pytest.mark.asyncio
async def test_asr_reverify_uses_vibevoice_with_hotwords(tmp_path: pytest.TempPathFactory) -> None:
    from hevi.tongjian.assemble import _asr_reverify

    audio = tmp_path / "nar.wav"
    audio.write_bytes(b"fake-wav")
    script = Script(
        lines=[
            ScriptLine(line_id="LN001", act=1, type="dialogue", speaker="c_zhihu", text="智伯索地")
        ]
    )
    with patch(
        "hevi.tongjian.assemble._vibevoice_asr_utterances",
        AsyncMock(return_value=[{"speaker": "c_zhihu", "text": "智伯索地"}]),
    ):
        cer, note = await _asr_reverify(audio, script, hotwords=["智伯", "晋阳"])
    assert cer is not None and cer == 0.0  # 文本一致
    assert note == ""  # speaker 匹配 → 无 warning


@pytest.mark.asyncio
async def test_asr_reverify_falls_back_to_whisper(tmp_path: pytest.TempPathFactory) -> None:
    from hevi.tongjian.assemble import _asr_reverify

    audio = tmp_path / "nar.wav"
    audio.write_bytes(b"fake-wav")
    script = Script(lines=[])
    with (
        patch("hevi.tongjian.assemble._vibevoice_asr_utterances", AsyncMock(return_value=[])),
        patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("whisper 未安装"),
        ),
    ):
        cer, note = await _asr_reverify(audio, script)
    assert cer is None
    assert "whisper" in note  # 回退失败也给出原因, 不抛错


# ── gen-engine /api/ai/asr 端点(模型缺失 501) ─────────────────────────────


def test_gen_engine_asr_endpoint_501_without_model() -> None:
    import os
    import sys

    sys.path.insert(0, "services/gen_engine")
    from ai_routes import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/api/ai")
    os.environ.pop("VIBEVOICE_ASR_MODEL_DIR", None)
    client = TestClient(app)
    r = client.post(
        "/api/ai/asr",
        files={"audio": ("a.wav", b"fake", "audio/wav")},
        data={"language": "zh", "hotwords": "智伯"},
    )
    assert r.status_code == 501
    assert "VibeVoice-ASR" in r.json()["detail"]
    client.close()
    sys.path.remove("services/gen_engine")
