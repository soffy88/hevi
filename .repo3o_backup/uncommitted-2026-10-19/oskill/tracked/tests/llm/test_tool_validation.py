"""Tests for tool_call_validator."""

from __future__ import annotations

import pytest

from oskill.llm.tool_validation import tool_call_validator

# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

SIMPLE_SCHEMA = {
    "name": "get_weather",
    "description": "Get weather for a location",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "unit": {"type": "string"},
            "temperature": {"type": "number"},
            "count": {"type": "integer"},
            "active": {"type": "boolean"},
            "tags": {"type": "array"},
        },
        "required": ["location"],
    },
}


def make_call(**args) -> dict:
    return {"name": "get_weather", "arguments": args}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tool_validator_valid_call_passes():
    call = make_call(location="London", unit="celsius")
    result = tool_call_validator(call, SIMPLE_SCHEMA)
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["tool_name"] == "get_weather"


def test_tool_validator_missing_required_arg_fails():
    call = {"name": "get_weather", "arguments": {"unit": "celsius"}}  # location missing
    result = tool_call_validator(call, SIMPLE_SCHEMA)
    assert result["valid"] is False
    paths = [e["path"] for e in result["errors"]]
    assert any("location" in p for p in paths)


def test_tool_validator_wrong_arg_type_fails():
    call = make_call(location=123)  # location should be string
    result = tool_call_validator(call, SIMPLE_SCHEMA, strict=False)
    assert result["valid"] is False
    type_errors = [e for e in result["errors"] if "location" in e["path"]]
    assert len(type_errors) >= 1
    assert type_errors[0]["expected"] == "string"


def test_tool_validator_extra_args_in_strict_mode_fails():
    call = make_call(location="Paris", unknown_field="oops")
    result = tool_call_validator(call, SIMPLE_SCHEMA, strict=True)
    assert result["valid"] is False
    extra_errors = [e for e in result["errors"] if "unknown_field" in e["path"]]
    assert len(extra_errors) >= 1


def test_tool_validator_extra_args_non_strict_warns():
    call = make_call(location="Berlin", extra_key="value")
    result = tool_call_validator(call, SIMPLE_SCHEMA, strict=False)
    assert result["valid"] is True
    assert any("extra_key" in w or "Unexpected" in w for w in result["warnings"])


def test_tool_validator_unknown_tool_name_fails():
    call = {"name": "wrong_tool", "arguments": {"location": "NYC"}}
    result = tool_call_validator(call, SIMPLE_SCHEMA)
    assert result["valid"] is False
    name_errors = [e for e in result["errors"] if e["path"] == "name"]
    assert len(name_errors) == 1
    assert name_errors[0]["expected"] == "get_weather"
    assert name_errors[0]["actual"] == "wrong_tool"


def test_tool_validator_coerce_str_to_int():
    call = make_call(location="Tokyo", count="42")
    result = tool_call_validator(call, SIMPLE_SCHEMA, coerce_types=True)
    assert result["valid"] is True
    assert result["normalized_arguments"]["count"] == 42
    assert isinstance(result["normalized_arguments"]["count"], int)


def test_tool_validator_coerce_str_to_float():
    call = make_call(location="Seoul", temperature="23.5")
    result = tool_call_validator(call, SIMPLE_SCHEMA, coerce_types=True)
    assert result["valid"] is True
    assert result["normalized_arguments"]["temperature"] == pytest.approx(23.5)


def test_tool_validator_coerce_disabled_by_default():
    call = make_call(location="Madrid", count="5")
    result = tool_call_validator(call, SIMPLE_SCHEMA)  # coerce_types=False by default
    assert result["valid"] is False
    type_errors = [e for e in result["errors"] if "count" in e["path"]]
    assert len(type_errors) >= 1


def test_tool_validator_returns_normalized_arguments():
    call = make_call(location="Rome", unit="metric")
    result = tool_call_validator(call, SIMPLE_SCHEMA)
    assert "normalized_arguments" in result
    assert isinstance(result["normalized_arguments"], dict)
    assert result["normalized_arguments"]["location"] == "Rome"


@pytest.mark.academic_reference
def test_tool_validator_anthropic_input_key():
    """Anthropic function calling uses 'input' instead of 'arguments'.

    Reference: Anthropic API Documentation (2024). Tool use / function calling
    format uses {'name': ..., 'input': {...}} rather than the OpenAI
    {'name': ..., 'arguments': '...'} format.
    See: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
    """
    # Anthropic-style tool call uses 'input' key
    anthropic_call = {
        "name": "get_weather",
        "input": {"location": "Sydney", "unit": "celsius"},
    }
    result = tool_call_validator(anthropic_call, SIMPLE_SCHEMA)
    assert result["valid"] is True
    assert result["normalized_arguments"]["location"] == "Sydney"
    assert result["tool_name"] == "get_weather"
