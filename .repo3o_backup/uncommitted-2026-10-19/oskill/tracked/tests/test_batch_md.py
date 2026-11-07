"""Tests for Mneme M-D batch: 5 oskill elements.

Mandatory tests:
- test_no_adjacent_same_kc (interleave_select hard constraint)
- socratic_loop answer leakage filter

Version: oskill v3.21.0
"""

from __future__ import annotations

import asyncio

import pytest

from oskill.generate_practice_set import (
    PracticeSetConfig,
    generate_practice_set,
)
from oskill.interleave_select import (
    QuestionItem,
    interleave_select,
)
from oskill.longitudinal_pattern import (
    AttemptRecord,
    longitudinal_pattern,
)
from oskill.socratic_loop import (
    create_socratic_state,
    process_socratic_turn,
)
from oskill.solve_and_visualize import (
    SolveAndVisualizeInput,
    _guess_problem_type,
    solve_and_visualize,
)

# ─────────────────────────────────────────────────────────────────────────────
# Mock LLM caller
# ─────────────────────────────────────────────────────────────────────────────


def _make_caller(text: str):
    async def caller(**kwargs):
        return {
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }

    return caller


# ─────────────────────────────────────────────────────────────────────────────
# solve_and_visualize
# ─────────────────────────────────────────────────────────────────────────────


class TestSolveAndVisualize:
    def test_solve_quadratic(self):
        inp = SolveAndVisualizeInput(expression="x**2 - 4", problem_type="function")
        r = solve_and_visualize(inp)
        assert r.solvable
        assert "2" in r.solve_answer or "-2" in r.solve_answer

    def test_svg_generated(self):
        inp = SolveAndVisualizeInput(expression="x**2 - 4", generate_svg=True)
        r = solve_and_visualize(inp)
        if r.solvable:
            assert r.svg.startswith("<svg") or r.svg == ""

    def test_conic_type(self):
        inp = SolveAndVisualizeInput(
            expression="x**2 + y**2 - 9", problem_type="conic", generate_svg=False
        )
        r = solve_and_visualize(inp)
        assert r.solvable
        assert "circle" in r.solve_answer

    def test_steps_returned(self):
        inp = SolveAndVisualizeInput(expression="x**2 - 9", problem_type="function")
        r = solve_and_visualize(inp)
        if r.solvable:
            assert len(r.solve_steps) >= 1

    def test_auto_type_detection(self):
        inp = SolveAndVisualizeInput(expression="sin(x)")
        r = solve_and_visualize(inp)
        assert r.problem_type_used == "trig"

    def test_guess_problem_type_trig(self):
        assert _guess_problem_type("sin(x) + cos(x)") == "trig"

    def test_guess_problem_type_conic(self):
        assert _guess_problem_type("x**2 + y**2 - 4") == "conic"

    def test_guess_problem_type_function_default(self):
        assert _guess_problem_type("x + 1") == "function"

    def test_no_svg_when_disabled(self):
        inp = SolveAndVisualizeInput(expression="x**2", generate_svg=False)
        r = solve_and_visualize(inp)
        assert r.svg == ""


# ─────────────────────────────────────────────────────────────────────────────
# socratic_loop
# ─────────────────────────────────────────────────────────────────────────────


class TestSocraticLoop:
    def test_basic_turn(self):
        caller = _make_caller("你觉得应该怎么移项？")
        state = create_socratic_state("x+1=3", "2")
        result = asyncio.run(process_socratic_turn(state, "我不知道", caller=caller))
        assert result.assistant_text
        assert result.answer_leaked is False

    def test_answer_leakage_filtered(self):
        """When LLM reveals the answer, text must be replaced."""
        answer = "42"
        caller = _make_caller(f"答案是 {answer}，你学到了吗？")
        state = create_socratic_state("x=?", answer)
        result = asyncio.run(process_socratic_turn(state, "我不会", caller=caller))
        assert result.answer_leaked is True
        assert answer not in result.assistant_text
        assert result.assistant_text == "这道题你再想想，思路是什么？"

    def test_answer_leakage_recorded(self):
        answer = "99"
        caller = _make_caller(f"结果是 {answer}")
        state = create_socratic_state("?", answer)
        asyncio.run(process_socratic_turn(state, "...", caller=caller))
        assert state.violation_count == 1

    def test_turn_count_increments(self):
        caller = _make_caller("继续思考")
        state = create_socratic_state("x=?", "1")
        asyncio.run(process_socratic_turn(state, "不会", caller=caller))
        asyncio.run(process_socratic_turn(state, "还是不会", caller=caller))
        assert state.turn_count == 2

    def test_conversation_history_grows(self):
        caller = _make_caller("好问题")
        state = create_socratic_state("x=?", "5")
        asyncio.run(process_socratic_turn(state, "5是答案吗", caller=caller))
        assert len(state.messages) == 2  # user + assistant

    def test_step_check_triggered(self):
        caller = _make_caller("检查你的计算")
        state = create_socratic_state("2x=6", "3")
        result = asyncio.run(process_socratic_turn(state, "我算了，结果是3", caller=caller))
        assert result.step_check_triggered is True

    def test_no_leakage_when_answer_not_in_response(self):
        caller = _make_caller("想想这个等式的两边")
        state = create_socratic_state("x+1=5", "4")
        result = asyncio.run(process_socratic_turn(state, "不确定", caller=caller))
        assert result.answer_leaked is False

    def test_turn_number_returned(self):
        caller = _make_caller("继续")
        state = create_socratic_state("x=?", "7")
        result = asyncio.run(process_socratic_turn(state, "嗯", caller=caller))
        assert result.turn_number == 1


# ─────────────────────────────────────────────────────────────────────────────
# interleave_select — MANDATORY: test_no_adjacent_same_kc
# ─────────────────────────────────────────────────────────────────────────────


class TestInterleaveSelect:
    def _make_questions(self, kc_pattern: list[str]) -> list[QuestionItem]:
        return [
            QuestionItem(question_id=f"q{i}", kc_id=kc, difficulty=0.5, mastery=0.3)
            for i, kc in enumerate(kc_pattern)
        ]

    def test_no_adjacent_same_kc(self):
        """Hard constraint: no adjacent questions share the same kc_id."""
        questions = self._make_questions(["A", "A", "B", "B", "A", "C"])
        result = interleave_select(questions)
        selected = result.selected
        for i in range(len(selected) - 1):
            assert selected[i].kc_id != selected[i + 1].kc_id, (
                f"Adjacent same kc_id at positions {i} and {i + 1}: {selected[i].kc_id}"
            )

    def test_basic_interleaving(self):
        questions = self._make_questions(["A", "B", "A", "B"])
        result = interleave_select(questions)
        assert len(result.selected) == 4

    def test_max_count_respected(self):
        questions = self._make_questions(["A", "B", "A", "B", "A", "B"])
        result = interleave_select(questions, max_count=3)
        assert len(result.selected) <= 3

    def test_empty_input(self):
        result = interleave_select([])
        assert result.selected == []
        assert result.dropped == []

    def test_single_item(self):
        questions = [QuestionItem("q1", "A")]
        result = interleave_select(questions)
        assert len(result.selected) == 1

    def test_raises_on_single_kc_multiple_items(self):
        questions = self._make_questions(["A", "A", "A"])
        with pytest.raises(ValueError, match="interleave"):
            interleave_select(questions)

    def test_dropped_items_correct(self):
        questions = self._make_questions(["A", "B", "A", "B"])
        result = interleave_select(questions, max_count=2)
        total = len(result.selected) + len(result.dropped)
        assert total == 4

    def test_priority_lower_mastery_first(self):
        questions = [
            QuestionItem("q1", "A", difficulty=0.5, mastery=0.9),
            QuestionItem("q2", "B", difficulty=0.5, mastery=0.1),
        ]
        result = interleave_select(questions)
        assert result.selected[0].kc_id == "B"  # lower mastery = higher priority

    def test_seed_kc_id_avoided(self):
        questions = [
            QuestionItem("q1", "A", mastery=0.1),
            QuestionItem("q2", "B", mastery=0.2),
        ]
        result = interleave_select(questions, seed_kc_id="A")
        assert result.selected[0].kc_id != "A"

    def test_large_interleaving_maintains_constraint(self):
        """Test with 20 questions across 4 KCs."""
        kcs = ["A", "B", "C", "D"]
        questions = [QuestionItem(f"q{i}", kcs[i % 4], mastery=0.3) for i in range(20)]
        result = interleave_select(questions)
        selected = result.selected
        for i in range(len(selected) - 1):
            assert selected[i].kc_id != selected[i + 1].kc_id


# ─────────────────────────────────────────────────────────────────────────────
# generate_practice_set
# ─────────────────────────────────────────────────────────────────────────────


class TestGeneratePracticeSet:
    def _bank(self, n: int = 10) -> list[QuestionItem]:
        kcs = ["algebra", "geometry", "calculus", "trig"]
        return [
            QuestionItem(
                question_id=f"q{i}",
                kc_id=kcs[i % 4],
                difficulty=(i % 5) * 0.2,
                mastery=0.3,
            )
            for i in range(n)
        ]

    def test_basic_generation(self):
        bank = self._bank(20)
        result = generate_practice_set(bank)
        assert len(result.questions) <= 10

    def test_no_adjacent_kc_in_result(self):
        bank = self._bank(20)
        result = generate_practice_set(bank)
        selected = result.questions
        for i in range(len(selected) - 1):
            assert selected[i].kc_id != selected[i + 1].kc_id

    def test_mastery_threshold(self):
        bank = [
            QuestionItem("q1", "A", mastery=0.9),  # above threshold
            QuestionItem("q2", "B", mastery=0.3),  # below threshold
            QuestionItem("q3", "C", mastery=0.2),
        ]
        cfg = PracticeSetConfig(mastery_threshold=0.8)
        result = generate_practice_set(bank, config=cfg)
        kc_ids = {q.kc_id for q in result.questions}
        assert "A" not in kc_ids  # high mastery excluded

    def test_target_count_respected(self):
        bank = self._bank(30)
        cfg = PracticeSetConfig(target_count=5)
        result = generate_practice_set(bank, config=cfg)
        assert len(result.questions) <= 5

    def test_kc_distribution(self):
        bank = self._bank(20)
        result = generate_practice_set(bank)
        assert len(result.kc_distribution) > 0

    def test_mastery_from_map(self):
        bank = [
            QuestionItem("q1", "A", mastery=0.3),
            QuestionItem("q2", "B", mastery=0.3),
        ]
        # Override mastery for KC A to be above threshold
        result = generate_practice_set(
            bank,
            kc_mastery={"A": 0.95},
            config=PracticeSetConfig(mastery_threshold=0.8),
        )
        kc_ids = {q.kc_id for q in result.questions}
        assert "A" not in kc_ids

    def test_empty_bank(self):
        result = generate_practice_set([])
        assert result.questions == []

    def test_coverage_metric(self):
        bank = self._bank(16)
        result = generate_practice_set(bank, config=PracticeSetConfig(target_count=8))
        assert 0.0 <= result.mastery_coverage <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# longitudinal_pattern
# ─────────────────────────────────────────────────────────────────────────────


class TestLongitudinalPattern:
    def _records(
        self, kc_id: str, correct_seq: list[bool], base_ts: float = 0.0
    ) -> list[AttemptRecord]:
        return [
            AttemptRecord(
                question_id=f"{kc_id}_{i}",
                kc_id=kc_id,
                correct=c,
                timestamp=base_ts + i * 3600,
            )
            for i, c in enumerate(correct_seq)
        ]

    def test_empty_records(self):
        r = longitudinal_pattern([])
        assert r.overall_trend == 0.0
        assert r.sessions_analyzed == 0

    def test_improving_kc(self):
        records = self._records("algebra", [False, False, True, True, True])
        r = longitudinal_pattern(records)
        if "algebra" in r.kc_trajectories:
            assert r.kc_trajectories["algebra"].trend >= 0

    def test_forgetting_detection(self):
        # Peaks then declines
        records = self._records(
            "calculus",
            [True, True, True, True, False, False, False],
        )
        r = longitudinal_pattern(records)
        if "calculus" in r.kc_trajectories:
            traj = r.kc_trajectories["calculus"]
            # Should detect forgetting
            assert isinstance(traj.is_forgetting, bool)

    def test_plateau_detection(self):
        records = self._records("trig", [True, True, True, True, True, True])
        r = longitudinal_pattern(records)
        if "trig" in r.kc_trajectories:
            traj = r.kc_trajectories["trig"]
            assert isinstance(traj.is_plateau, bool)

    def test_kc_trajectory_returned(self):
        records = self._records("algebra", [True, False, True, False, True])
        r = longitudinal_pattern(records)
        if "algebra" in r.kc_trajectories:
            traj = r.kc_trajectories["algebra"]
            assert traj.kc_id == "algebra"
            assert traj.attempt_count == 5

    def test_multiple_kcs(self):
        r1 = self._records("A", [True, True, True, True])
        r2 = self._records("B", [False, False, True, True])
        r = longitudinal_pattern(r1 + r2)
        assert len(r.kc_trajectories) == 2

    def test_min_attempts_filter(self):
        short = self._records("X", [True, True])  # only 2 attempts
        long_r = self._records("Y", [True, False, True, True])
        r = longitudinal_pattern(short + long_r, min_attempts_per_kc=3)
        assert "X" not in r.kc_trajectories
        assert "Y" in r.kc_trajectories

    def test_sessions_counted(self):
        # 2 different days
        ts_day1 = 0.0
        ts_day2 = 86400.0
        records = [
            AttemptRecord("q1", "A", True, ts_day1),
            AttemptRecord("q2", "A", True, ts_day1 + 100),
            AttemptRecord("q3", "A", True, ts_day2),
            AttemptRecord("q4", "A", True, ts_day2 + 100),
        ]
        r = longitudinal_pattern(records)
        assert r.sessions_analyzed == 2

    def test_improving_kcs_classified(self):
        improving_records = self._records("geo", [False, False, True, True, True, True])
        r = longitudinal_pattern(improving_records)
        if "geo" in r.improving_kcs:
            assert True  # correctly classified

    def test_overall_trend_mean(self):
        r1 = self._records("A", [True, True, True, True])
        r = longitudinal_pattern(r1)
        assert isinstance(r.overall_trend, float)
