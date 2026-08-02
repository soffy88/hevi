from __future__ import annotations

import pytest

from hevi.explainer.asr_verify import AsrVerificationError, character_error_rate, verify_audio
from hevi.explainer.assembly import cues_to_storyboard
from hevi.explainer.contracts import (
    ExplainerCapabilityError,
    ExplainerCue,
    ExplainerResearchRequest,
)
from hevi.explainer.research import research_and_generate


def _payload() -> dict:
    cue = {"time_range": "00:00-00:05", "visual_type": "voiceover", "text": "事实"}
    return {
        "facts": [{"claim": "事实", "source": "公开报告", "confidence": 0.9}],
        "hooks": [{"text": f"Hook {i}", "angle": "角度", "recommended": i == 0} for i in range(5)],
        "scripts": [
            {
                "id": letter,
                "title": f"版本 {letter}",
                "viewpoint": "数据",
                "hook": "Hook 0",
                "cues": [cue],
            }
            for letter in ("A", "B", "C")
        ],
    }


class _Researcher:
    async def research(self, _topic: str) -> dict:
        return {"facts": _payload()["facts"]}


class _Generator:
    async def generate(self, _topic: str, _research: dict) -> dict:
        return _payload()


@pytest.mark.asyncio
async def test_v6_research_returns_five_hooks_and_three_scripts() -> None:
    result = await research_and_generate(
        ExplainerResearchRequest(topic_or_url="测试主题"),
        researcher=_Researcher(),
        script_generator=_Generator(),
    )
    assert len(result.hooks) == 5
    assert len(result.scripts) == 3
    assert result.scripts[0].cues[0].visual_type == "voiceover"


@pytest.mark.asyncio
async def test_v6_research_rejects_incomplete_model_output() -> None:
    class Incomplete:
        async def research(self, _topic: str) -> dict:
            return {"facts": [], "hooks": [], "scripts": []}

    with pytest.raises(ExplainerCapabilityError, match="5 个 Hook"):
        await research_and_generate(
            ExplainerResearchRequest(topic_or_url="测试主题"), researcher=Incomplete()
        )


def test_v6_cues_keep_visual_scaffold_metadata_for_remotion() -> None:
    storyboard = cues_to_storyboard(
        "测试主题",
        [ExplainerCue(time_range="00:00-00:05", visual_type="remotion_chart", text="数据")],
    )
    assert storyboard.segments[0].visual_type == "remotion_chart"
    assert storyboard.segments[0].visual_config["time_range"] == "00:00-00:05"


def test_v6_character_error_rate_is_deterministic() -> None:
    assert character_error_rate("你好世界", "你好世界") == 0
    assert character_error_rate("你好世界", "你好") == 0.5


@pytest.mark.asyncio
async def test_v6_asr_verification_retries_and_reports_failure(tmp_path) -> None:
    audio = tmp_path / "segment.wav"
    audio.write_bytes(b"audio")
    attempts = 0

    async def bad_asr(_path):
        nonlocal attempts
        attempts += 1
        return {"text": "完全不同"}

    with pytest.raises(AsrVerificationError, match="CER"):
        await verify_audio("目标旁白", audio, asr=bad_asr, retries=2)
    assert attempts == 3
