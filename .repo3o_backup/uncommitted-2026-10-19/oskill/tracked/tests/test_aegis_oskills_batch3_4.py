from unittest.mock import MagicMock, patch

from obase.docker import ContainerInfo

from oskill import RetrievedDoc, Signal
from oskill.agentic_investigate_loop import agentic_investigate_loop
from oskill.restart_and_verify import restart_and_verify
from oskill.retrieve_and_synthesize import retrieve_and_synthesize
from oskill.runbook_match import runbook_match

# === agentic_investigate_loop tests ===


def test_agentic_investigate_loop_simple():
    mock_llm = MagicMock()
    mock_llm.return_value = {
        "content": "Root Cause Hypothesis: Network timeout. Confidence: 0.9",
        "stop_reason": "end_turn",
        "tool_calls": [],
    }

    signal = Signal(source="test", severity="warning")
    result = agentic_investigate_loop(signal=signal, available_tool_names=[], llm=mock_llm)

    assert result.stopped_reason == "llm_decided_stop"
    assert result.final_conclusion["confidence"] == 0.9
    assert result.final_conclusion["root_cause_hypothesis"] == "Network timeout."


# === retrieve_and_synthesize tests ===


def test_retrieve_and_synthesize_basic():
    mock_llm = MagicMock()
    mock_llm.return_value = {"content": "The answer is here. Confidence: 0.8"}

    def mock_search(q, c, k):
        return [RetrievedDoc(doc_id="1", content="Fact 1", score=1.0)]

    result = retrieve_and_synthesize(
        query="test query", corpus_id="test_corpus", llm=mock_llm, vector_search_fn=mock_search
    )

    assert result.confidence == 0.8
    assert len(result.retrieved_docs) == 1


# === runbook_match tests ===


def test_runbook_match_rule_based():
    root_cause = {"root_cause_hypothesis": "Database connection error"}
    plugins = [{"name": "db_fix", "matcher": {"error_pattern": "Database connection"}}]

    result = runbook_match(root_cause=root_cause, available_plugins=plugins)
    assert result.matched_plugin["name"] == "db_fix"
    assert result.match_score == 0.9


# === restart_and_verify tests ===


def test_restart_and_verify_success():
    with patch("oskill.restart_and_verify.docker_container_inspect") as mock_inspect:
        with patch("oskill.restart_and_verify.docker_container_restart"):
            mock_inspect.return_value = ContainerInfo(
                container_id="test",
                name="test",
                image="img",
                state="running",
                status="running",
                started_at=None,
                finished_at=None,
                exit_code=None,
                health=None,
                restart_count=0,
                labels={},
                ports=[],
                mounts=[],
            )

            result = restart_and_verify(container_id="test", health_check_interval_sec=1)
            assert result.restarted
            assert result.verified_healthy
