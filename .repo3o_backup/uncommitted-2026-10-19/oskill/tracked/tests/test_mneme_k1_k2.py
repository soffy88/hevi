"""Tests for K-1 and K-2 of the Mneme speech/essay batch.

K-1: english_speaking_practice  (≥8 tests)
K-2: essay_assessment           (≥8 tests)
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest
from oprim._mneme_speech_types import (
    EssayAssessmentInput,
    EssayAssessmentResult,
    PronunciationResult,
    SpeakingPracticeResult,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _b64(text: str = "audio") -> str:
    return base64.b64encode(text.encode()).decode()


def _pron(
    overall: float = 0.8, fluency: float = 0.75, accuracy: float = 0.85
) -> PronunciationResult:
    return PronunciationResult(
        overall_score=overall, fluency_score=fluency, accuracy_score=accuracy, word_scores=[]
    )


def _make_tts():
    return AsyncMock(return_value=_b64("tts-out"))


def _make_stt(text: str = "I love learning English"):
    return AsyncMock(return_value=text)


def _make_pron_eval(overall: float = 0.8):
    return AsyncMock(return_value=_pron(overall))


def _make_llm(text: str = "Great job! What else would you like to share？"):
    async def caller(*, messages, max_tokens=256, **kwargs):
        return {"content": [{"type": "text", "text": text}]}

    return caller


_SAMPLE_ESSAY = """\
科技的发展改变了我们的生活方式。从手机到电脑，人们的通信变得更加便捷。

然而，科技也带来了一些问题。人们越来越依赖电子设备，面对面的交流减少了。

我认为，我们应该理性使用科技，在享受便利的同时，不忘记人与人之间真实的情感联系。
""".strip()


# ===========================================================================
# K-1: english_speaking_practice
# ===========================================================================


class TestEnglishSpeakingPractice:
    async def test_returns_speaking_practice_result(self):
        from oskill._english_speaking_practice import english_speaking_practice

        result = await english_speaking_practice(
            topic="Tell me about your favourite season",
            max_turns=1,
            tts=_make_tts(),
            stt=_make_stt(),
            pronunciation_eval=_make_pron_eval(),
            llm=_make_llm(),
        )
        assert isinstance(result, SpeakingPracticeResult)

    async def test_turn_count_matches_max_turns(self):
        from oskill._english_speaking_practice import english_speaking_practice

        result = await english_speaking_practice(
            topic="Sports",
            max_turns=3,
            tts=_make_tts(),
            stt=_make_stt(),
            pronunciation_eval=_make_pron_eval(),
            llm=_make_llm(),
        )
        assert len(result.turns) == 3

    async def test_pronunciation_scores_collected_per_turn(self):
        from oskill._english_speaking_practice import english_speaking_practice

        result = await english_speaking_practice(
            topic="Food",
            max_turns=2,
            tts=_make_tts(),
            stt=_make_stt(),
            pronunciation_eval=_make_pron_eval(overall=0.9),
            llm=_make_llm(),
        )
        assert len(result.pronunciation_scores) == 2
        assert all(p.overall_score == pytest.approx(0.9) for p in result.pronunciation_scores)

    async def test_overall_progress_is_mean_of_scores(self):
        from oskill._english_speaking_practice import english_speaking_practice

        pron_mock = AsyncMock(side_effect=[_pron(0.6), _pron(0.8)])
        result = await english_speaking_practice(
            topic="Hobbies",
            max_turns=2,
            tts=_make_tts(),
            stt=_make_stt(),
            pronunciation_eval=pron_mock,
            llm=_make_llm(),
        )
        assert result.overall_progress == pytest.approx(0.7)

    async def test_zero_max_turns_raises(self):
        from oskill._english_speaking_practice import english_speaking_practice

        with pytest.raises(ValueError, match="max_turns"):
            await english_speaking_practice(
                topic="Test",
                max_turns=0,
                tts=_make_tts(),
                stt=_make_stt(),
                pronunciation_eval=_make_pron_eval(),
                llm=_make_llm(),
            )

    async def test_empty_topic_raises(self):
        from oskill._english_speaking_practice import english_speaking_practice

        with pytest.raises(ValueError, match="topic"):
            await english_speaking_practice(
                topic="   ",
                max_turns=1,
                tts=_make_tts(),
                stt=_make_stt(),
                pronunciation_eval=_make_pron_eval(),
                llm=_make_llm(),
            )

    async def test_feedback_encouraging_guard_removes_correction_lines(self):
        """LLM returning 'You should say X' lines are filtered out."""
        from oskill._english_speaking_practice import english_speaking_practice

        bad_llm_text = "You should say 'I enjoy' not 'I enjoyable'.\nGreat effort though! What else do you like？"

        async def bad_llm(*, messages, max_tokens=256, **kwargs):
            return {"content": [{"type": "text", "text": bad_llm_text}]}

        result = await english_speaking_practice(
            topic="Hobbies",
            max_turns=1,
            tts=_make_tts(),
            stt=_make_stt("I enjoyable football"),
            pronunciation_eval=_make_pron_eval(),
            llm=bad_llm,
        )
        ai_feedback = result.turns[0]["ai_feedback"]
        assert "You should say" not in ai_feedback

    async def test_turn_structure_has_required_keys(self):
        from oskill._english_speaking_practice import english_speaking_practice

        result = await english_speaking_practice(
            topic="Travel",
            max_turns=1,
            tts=_make_tts(),
            stt=_make_stt("I want to visit Japan"),
            pronunciation_eval=_make_pron_eval(),
            llm=_make_llm(),
        )
        turn = result.turns[0]
        assert "student_text" in turn
        assert "ai_feedback" in turn
        assert "pronunciation" in turn
        assert "turn" in turn

    async def test_string_content_response_from_llm(self):
        """LLM may return content as plain string instead of block list."""
        from oskill._english_speaking_practice import english_speaking_practice

        async def str_llm(*, messages, max_tokens=256, **kwargs):
            return {"content": "Keep going! What do you think about that？"}

        result = await english_speaking_practice(
            topic="Music",
            max_turns=1,
            tts=_make_tts(),
            stt=_make_stt("I like jazz"),
            pronunciation_eval=_make_pron_eval(),
            llm=str_llm,
        )
        assert result.turns[0]["ai_feedback"] != ""


# ===========================================================================
# K-2: essay_assessment
# ===========================================================================


class TestEssayAssessment:
    def _make_llm_with_questions(self, questions=None):
        if questions is None:
            questions = [
                "你认为这段论述有什么可以补充的？",
                "这个例子能否更有说服力？",
                "结尾是否完整表达了你的观点？",
            ]

        async def caller(*, messages, max_tokens=512, **kwargs):
            return {
                "content": [{"type": "text", "text": json.dumps(questions, ensure_ascii=False)}]
            }

        return caller

    async def test_returns_essay_assessment_result(self):
        from oskill._essay_assessment import essay_assessment

        inp = EssayAssessmentInput(essay_text=_SAMPLE_ESSAY)
        result = await essay_assessment(inp, llm=self._make_llm_with_questions())
        assert isinstance(result, EssayAssessmentResult)

    async def test_rubric_scores_all_present(self):
        from oskill._essay_assessment import essay_assessment

        inp = EssayAssessmentInput(essay_text=_SAMPLE_ESSAY)
        result = await essay_assessment(inp, llm=self._make_llm_with_questions())
        assert set(result.rubric_scores.keys()) == {"结构", "立意", "语言", "格式"}

    async def test_all_rubric_scores_in_range(self):
        from oskill._essay_assessment import essay_assessment

        inp = EssayAssessmentInput(essay_text=_SAMPLE_ESSAY)
        result = await essay_assessment(inp, llm=self._make_llm_with_questions())
        for dim, score in result.rubric_scores.items():
            assert 0.0 <= score <= 100.0, f"{dim}={score}"

    async def test_guidance_questions_end_with_question_mark(self):
        from oskill._essay_assessment import essay_assessment

        questions = ["这段论证有什么问题", "你的例子足够具体吗"]  # no ？
        inp = EssayAssessmentInput(essay_text=_SAMPLE_ESSAY)
        result = await essay_assessment(inp, llm=self._make_llm_with_questions(questions))
        for q in result.guidance_questions:
            assert q.endswith("？"), f"Question does not end with ？: {q!r}"

    async def test_empty_essay_raises(self):
        from oskill._essay_assessment import essay_assessment

        with pytest.raises(ValueError, match="essay_text"):
            await essay_assessment(
                EssayAssessmentInput(essay_text=""),
                llm=self._make_llm_with_questions(),
            )

    async def test_revision_needed_true_for_short_essay(self):
        from oskill._essay_assessment import essay_assessment

        # Very short essay → low scores → revision_needed = True
        short_inp = EssayAssessmentInput(essay_text="科技好。")
        result = await essay_assessment(short_inp, llm=self._make_llm_with_questions())
        assert result.revision_needed is True

    async def test_revision_needed_false_for_good_essay(self):
        # Patch rubric_score to return high scores
        from unittest.mock import patch

        from oskill._essay_assessment import essay_assessment

        with patch(
            "oskill._essay_assessment.rubric_score",
            return_value={"结构": 90.0, "立意": 88.0, "语言": 85.0, "格式": 92.0},
        ):
            result = await essay_assessment(
                EssayAssessmentInput(essay_text=_SAMPLE_ESSAY),
                llm=self._make_llm_with_questions(),
            )
        assert result.revision_needed is False

    async def test_essay_guide_not_imported(self):
        """CI guard: essay_guide must not be imported by essay_assessment."""
        import importlib
        import sys

        for key in list(sys.modules.keys()):
            if "essay_assessment" in key:
                del sys.modules[key]
        mod = importlib.import_module("oskill._essay_assessment")
        source = open(mod.__file__).read()
        assert "import essay_guide" not in source

    async def test_custom_rubric_respected(self):
        from oskill._essay_assessment import essay_assessment

        custom_rubric = {"论点": 0.5, "例证": 0.5}
        inp = EssayAssessmentInput(essay_text=_SAMPLE_ESSAY, essay_type="议论文")
        result = await essay_assessment(
            inp, llm=self._make_llm_with_questions(), rubric=custom_rubric
        )
        assert set(result.rubric_scores.keys()) == {"论点", "例证"}

    async def test_llm_plain_text_questions_parsed(self):
        """LLM returning line-by-line questions (not JSON) still works."""
        from oskill._essay_assessment import essay_assessment

        async def line_llm(*, messages, max_tokens=512, **kwargs):
            return {
                "content": "1. 你的论点是否清晰？\n2. 能否补充更多例子？\n3. 结尾表达了什么观点"
            }

        inp = EssayAssessmentInput(essay_text=_SAMPLE_ESSAY)
        result = await essay_assessment(inp, llm=line_llm)
        assert len(result.guidance_questions) >= 1
        for q in result.guidance_questions:
            assert q.endswith("？")
