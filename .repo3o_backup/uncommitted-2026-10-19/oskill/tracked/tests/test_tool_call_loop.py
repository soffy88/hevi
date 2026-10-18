from unittest.mock import MagicMock

import pytest

from oskill.tool_call_loop import tool_call_loop


def test_tool_call_loop_no_tool():
    llm = MagicMock()
    llm.return_value = {
        "role": "assistant",
        "content": "Hello",
        "tool_calls": [],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    res = tool_call_loop(
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=[],
        tool_handler=MagicMock(),
        llm=llm,
    )

    assert res["stop_reason"] == "end_turn"
    assert res["total_input_tokens"] == 10
    assert len(res["steps"]) == 0


def test_tool_call_loop_single_tool():
    llm = MagicMock()
    # Turn 1: LLM calls tool
    llm.side_effect = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call1", "name": "get_weather", "input": {"city": "Shanghai"}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
        # Turn 2: LLM responds after tool result
        {
            "role": "assistant",
            "content": "It is sunny in Shanghai.",
            "tool_calls": [],
            "usage": {"input_tokens": 20, "output_tokens": 10},
        },
    ]

    handler = MagicMock(return_value={"temp": 25})

    res = tool_call_loop(
        initial_messages=[{"role": "user", "content": "weather?"}],
        tools=[{"name": "get_weather"}],
        tool_handler=handler,
        llm=llm,
    )

    assert res["stop_reason"] == "end_turn"
    assert res["total_input_tokens"] == 30
    assert len(res["steps"]) == 1
    assert res["steps"][0]["tool_calls"][0]["output"] == {"temp": 25}
    handler.assert_called_with("get_weather", {"city": "Shanghai"})


def test_tool_call_loop_max_steps():
    llm = MagicMock()
    # Always calls tool
    llm.return_value = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c", "name": "t", "input": {}}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    res = tool_call_loop(
        initial_messages=[],
        tools=[],
        tool_handler=MagicMock(return_value="ok"),
        llm=llm,
        max_steps=3,
    )

    assert res["stop_reason"] == "max_steps"
    assert len(res["steps"]) == 3


def test_tool_call_loop_tool_error():
    llm = MagicMock()
    llm.return_value = {
        "role": "assistant",
        "tool_calls": [{"id": "c", "name": "fail_tool", "input": {}}],
        "usage": {},
    }

    handler = MagicMock(side_effect=ValueError("tool failed"))

    res = tool_call_loop(initial_messages=[], tools=[], tool_handler=handler, llm=llm)

    assert res["stop_reason"] == "tool_error"
    assert "tool failed" in res["steps"][0]["error"]


def test_tool_call_loop_on_step():
    llm = MagicMock()
    llm.side_effect = [
        {"role": "assistant", "tool_calls": [{"id": "c1", "name": "t1", "input": {}}], "usage": {}},
        {"role": "assistant", "content": "done", "tool_calls": [], "usage": {}},
    ]

    on_step = MagicMock()
    tool_call_loop(
        initial_messages=[],
        tools=[],
        tool_handler=MagicMock(return_value="ok"),
        llm=llm,
        on_step=on_step,
    )

    assert on_step.call_count == 1


def test_tool_call_loop_openai_style():
    llm = MagicMock()
    llm.side_effect = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "c", "name": "t", "function": {"arguments": '{"a": 1}'}}],
            "usage": {},
        },
        {"role": "assistant", "content": "ok", "tool_calls": [], "usage": {}},
    ]

    handler = MagicMock(return_value="res")
    tool_call_loop(initial_messages=[], tools=[], tool_handler=handler, llm=llm)

    assert handler.call_args[0][1] == {"a": 1}


def test_tool_call_loop_multi_tool_one_turn():
    llm = MagicMock()
    llm.side_effect = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "c1", "name": "t1", "input": {}},
                {"id": "c2", "name": "t2", "input": {}},
            ],
            "usage": {},
        },
        {"role": "assistant", "content": "ok", "tool_calls": [], "usage": {}},
    ]

    handler = MagicMock(return_value="ok")
    res = tool_call_loop(initial_messages=[], tools=[], tool_handler=handler, llm=llm)

    assert len(res["steps"][0]["tool_calls"]) == 2
    assert handler.call_count == 2


def test_tool_call_loop_llm_error():
    llm = MagicMock(side_effect=RuntimeError("LLM down"))
    with pytest.raises(RuntimeError, match="LLM down"):
        tool_call_loop(initial_messages=[], tools=[], tool_handler=MagicMock(), llm=llm)


def test_tool_call_loop_assistant_no_role():
    llm = MagicMock()
    llm.return_value = {"content": "No role provided", "tool_calls": [], "usage": {}}
    res = tool_call_loop(initial_messages=[], tools=[], tool_handler=MagicMock(), llm=llm)
    assert res["final_message"]["role"] == "assistant"


def test_tool_call_loop_openai_json_error():
    llm = MagicMock()
    llm.side_effect = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "c", "name": "t", "function": {"arguments": "not-json"}}],
            "usage": {},
        },
        {"role": "assistant", "content": "ok", "tool_calls": [], "usage": {}},
    ]
    handler = MagicMock(return_value="res")
    tool_call_loop(initial_messages=[], tools=[], tool_handler=handler, llm=llm)
    # tool_input should be "not-json" string
    assert handler.call_args[0][1] == "not-json"


def test_tool_call_loop_message_ordering():
    llm_responses = [
        {"role": "assistant", "tool_calls": [{"id": "c", "name": "t", "input": {}}], "usage": {}},
        {"role": "assistant", "content": "final", "tool_calls": [], "usage": {}},
    ]

    # We want to capture the messages passed to LLM in the second call
    captured_messages = []

    def llm_side_effect(**kwargs):
        captured_messages.append(list(kwargs["messages"]))
        return llm_responses[len(captured_messages) - 1]

    llm_with_capture = MagicMock(side_effect=llm_side_effect)
    tool_call_loop(
        initial_messages=[{"role": "user", "content": "init"}],
        tools=[],
        tool_handler=MagicMock(return_value="tool_res"),
        llm=llm_with_capture,
    )

    # Second call should have: user, assistant (with tool_calls), tool (with result)
    assert len(captured_messages[1]) == 3
    assert captured_messages[1][0]["role"] == "user"
    assert captured_messages[1][1]["role"] == "assistant"
    assert "tool_calls" in captured_messages[1][1]
    assert captured_messages[1][2]["role"] == "tool"
    assert captured_messages[1][2]["content"] == "tool_res"
