"""Tests for oskill.llm.deterministic_call.deterministic_llm_call."""

import json
import warnings

import pytest

from oskill.llm._exceptions import LLMResponseFormatError, LLMResponseValidationError
from oskill.llm.deterministic_call import deterministic_llm_call


def _mock_client(response_text: str, stop_reason: str = "end_turn"):
    """Build a mock client_fn returning fixed text response."""

    def client_fn(messages, model, **kwargs):
        return {
            "content": response_text,
            "stop_reason": stop_reason,
            "input_tokens": 10,
            "output_tokens": 5,
        }

    return client_fn


# ── Happy path ──────────────────────────────────────────────────────────────


def test_deterministic_call_basic_text_response():
    """Returns text response and correct keys."""
    client = _mock_client("Hello World")
    result = deterministic_llm_call(
        "Say: {word}",
        {"word": "hello"},
        client,
        model="claude-haiku-4-5",
    )
    assert result["response"] == "Hello World"
    assert result["model"] == "claude-haiku-4-5"
    assert result["temperature"] == 0.0
    assert result["seed"] is None
    assert result["response_format"] == "text"


def test_deterministic_call_returns_all_required_keys():
    """All 9 required output keys are present."""
    client = _mock_client("ok")
    result = deterministic_llm_call("Prompt: {x}", {"x": "val"}, client, model="m")
    required = {
        "response",
        "prompt_rendered",
        "prompt_fingerprint",
        "model",
        "temperature",
        "seed",
        "response_format",
        "metadata",
        "timestamp_called",
    }
    assert required.issubset(result.keys())


def test_deterministic_call_renders_prompt():
    """prompt_rendered is the fully substituted prompt string."""
    client = _mock_client("ok")
    result = deterministic_llm_call(
        "Analyze: {ticker} on {date}",
        {"ticker": "AAPL", "date": "2026-01-01"},
        client,
        model="m",
    )
    assert result["prompt_rendered"] == "Analyze: AAPL on 2026-01-01"


def test_deterministic_call_fingerprint_is_64_char_hex():
    """prompt_fingerprint is a 64-char lowercase hex string."""
    client = _mock_client("ok")
    result = deterministic_llm_call("{x}", {"x": "y"}, client, model="m")
    fp = result["prompt_fingerprint"]
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_deterministic_call_same_inputs_same_fingerprint():
    """Same inputs always produce the same fingerprint (determinism)."""
    client = _mock_client("ok")
    r1 = deterministic_llm_call("{x}", {"x": "y"}, client, model="m", seed=42)
    r2 = deterministic_llm_call("{x}", {"x": "y"}, client, model="m", seed=42)
    assert r1["prompt_fingerprint"] == r2["prompt_fingerprint"]


def test_deterministic_call_different_variables_different_fingerprint():
    """Different variables produce different fingerprints."""
    client = _mock_client("ok")
    r1 = deterministic_llm_call("{x}", {"x": "a"}, client, model="m")
    r2 = deterministic_llm_call("{x}", {"x": "b"}, client, model="m")
    assert r1["prompt_fingerprint"] != r2["prompt_fingerprint"]


def test_deterministic_call_json_response_format():
    """response_format='json' parses JSON response."""
    payload = {"signal": 0.5, "confidence": 0.9}
    client = _mock_client(json.dumps(payload))
    result = deterministic_llm_call("{p}", {"p": "x"}, client, model="m", response_format="json")
    assert result["response"] == payload


def test_deterministic_call_json_schema_valid():
    """Valid JSON response passes schema validation."""
    payload = {"action": "buy", "size": 100}
    client = _mock_client(json.dumps(payload))
    schema = {"type": "object", "required": ["action", "size"]}
    result = deterministic_llm_call(
        "{p}", {"p": "x"}, client, model="m", response_format="json", json_schema=schema
    )
    assert result["response"]["action"] == "buy"


def test_deterministic_call_metadata_populated():
    """metadata dict contains input_tokens, output_tokens, stop_reason."""
    client = _mock_client("ok")
    result = deterministic_llm_call("{x}", {"x": "v"}, client, model="m")
    meta = result["metadata"]
    assert meta["input_tokens"] == 10
    assert meta["output_tokens"] == 5
    assert meta["stop_reason"] == "end_turn"


def test_deterministic_call_seed_passed_to_client():
    """seed is recorded in result when provided."""
    client = _mock_client("ok")
    result = deterministic_llm_call("{x}", {"x": "v"}, client, model="m", seed=123)
    assert result["seed"] == 123


# ── Exception cases ──────────────────────────────────────────────────────────


def test_deterministic_call_missing_variable_raises_key_error():
    """Missing template variable raises KeyError."""
    client = _mock_client("ok")
    with pytest.raises(KeyError):
        deterministic_llm_call("{x} {y}", {"x": "only_x"}, client, model="m")


def test_deterministic_call_invalid_json_raises_format_error():
    """Non-JSON response with response_format='json' raises LLMResponseFormatError."""
    client = _mock_client("not valid json {{{")
    with pytest.raises(LLMResponseFormatError):
        deterministic_llm_call("{x}", {"x": "v"}, client, model="m", response_format="json")


def test_deterministic_call_schema_missing_required_raises_validation_error():
    """JSON response missing required field raises LLMResponseValidationError."""
    payload = {"action": "buy"}  # missing 'size'
    client = _mock_client(json.dumps(payload))
    schema = {"type": "object", "required": ["action", "size"]}
    with pytest.raises(LLMResponseValidationError):
        deterministic_llm_call(
            "{x}", {"x": "v"}, client, model="m", response_format="json", json_schema=schema
        )


def test_deterministic_call_schema_object_type_non_dict_raises():
    """Object schema validation fails when response is not a dict."""
    client = _mock_client(json.dumps([1, 2, 3]))  # a list, not object
    with pytest.raises(LLMResponseValidationError, match="object"):
        deterministic_llm_call(
            "{x}",
            {"x": "v"},
            client,
            model="m",
            response_format="json",
            json_schema={"type": "object", "required": []},
        )


def test_deterministic_call_schema_type_array_valid():
    """Array JSON schema type validation passes for a list."""
    payload = [1, 2, 3]
    client = _mock_client(json.dumps(payload))
    result = deterministic_llm_call(
        "{x}", {"x": "v"}, client, model="m", response_format="json", json_schema={"type": "array"}
    )
    assert result["response"] == [1, 2, 3]


def test_deterministic_call_schema_type_array_invalid_raises():
    """Array JSON schema type validation fails for non-list."""
    payload = {"not": "array"}
    client = _mock_client(json.dumps(payload))
    with pytest.raises(LLMResponseValidationError, match="array"):
        deterministic_llm_call(
            "{x}",
            {"x": "v"},
            client,
            model="m",
            response_format="json",
            json_schema={"type": "array"},
        )


def test_deterministic_call_schema_type_string_valid():
    """String JSON schema type validation passes for a string response."""
    payload = '"hello world"'
    client = _mock_client(payload)
    result = deterministic_llm_call(
        "{x}", {"x": "v"}, client, model="m", response_format="json", json_schema={"type": "string"}
    )
    assert result["response"] == "hello world"


def test_deterministic_call_schema_type_string_invalid_raises():
    """String JSON schema type validation fails for non-string."""
    client = _mock_client(json.dumps(42))
    with pytest.raises(LLMResponseValidationError, match="string"):
        deterministic_llm_call(
            "{x}",
            {"x": "v"},
            client,
            model="m",
            response_format="json",
            json_schema={"type": "string"},
        )


def test_deterministic_call_schema_type_number_valid():
    """Number JSON schema type validation passes for int/float."""
    client = _mock_client(json.dumps(3.14))
    result = deterministic_llm_call(
        "{x}", {"x": "v"}, client, model="m", response_format="json", json_schema={"type": "number"}
    )
    assert result["response"] == pytest.approx(3.14)


def test_deterministic_call_schema_type_number_invalid_raises():
    """Number JSON schema type validation fails for non-number."""
    client = _mock_client(json.dumps("not a number"))
    with pytest.raises(LLMResponseValidationError, match="number"):
        deterministic_llm_call(
            "{x}",
            {"x": "v"},
            client,
            model="m",
            response_format="json",
            json_schema={"type": "number"},
        )


def test_deterministic_call_temperature_nonzero_warns():
    """temperature > 0 emits UserWarning."""
    client = _mock_client("ok")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        deterministic_llm_call("{x}", {"x": "v"}, client, model="m", temperature=0.5)
    assert any(issubclass(x.category, UserWarning) for x in w)
    assert any("temperature" in str(x.message).lower() for x in w)


# ── Academic reference ────────────────────────────────────────────────────────


@pytest.mark.academic_reference
def test_deterministic_call_fingerprint_is_sha256_of_canonical_payload():
    """Fingerprint equals SHA-256(canonical_json(payload)) per oprim spec.

    Reference: arxiv 2601.15322 (Replayable Financial Agents, 2026).
    The determinism guarantee: same (template + variables + model + temp + seed)
    → identical prompt_fingerprint across runs and processes.
    """
    from oprim import canonical_json, sha256_hash

    template = "Analyze {ticker}"
    variables = {"ticker": "AAPL"}
    model = "claude-opus-4-7"
    temperature = 0.0
    seed = 42

    client = _mock_client("analysis result")
    result = deterministic_llm_call(
        template, variables, client, model=model, temperature=temperature, seed=seed
    )

    # Recompute the fingerprint independently
    audit_payload = {
        "template": template,
        "variables": variables,
        "model": model,
        "temperature": temperature,
        "seed": seed,
    }
    expected_fp = sha256_hash(canonical_json(audit_payload))

    assert result["prompt_fingerprint"] == expected_fp
