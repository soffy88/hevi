"""Deterministic LLM call wrapper with audit-ready output."""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from oprim import canonical_json, sha256_hash

from oskill.llm._exceptions import LLMResponseFormatError, LLMResponseValidationError


def deterministic_llm_call(
    prompt_template: str,
    variables: dict[str, Any],
    client_fn: Callable[..., dict],
    *,
    model: str,
    temperature: float = 0.0,
    seed: int | None = None,
    max_tokens: int = 1024,
    response_format: Literal["text", "json"] = "text",
    json_schema: dict | None = None,
) -> dict[str, Any]:
    """Deterministic LLM call wrapper with audit-ready output.

    Workflow (≥2 oprim calls):
        1. Render prompt by substituting variables into template
        2. Compute prompt_fingerprint via oprim.canonical_json + oprim.sha256_hash
        3. Call client_fn with deterministic parameters (temp=0, seed)
        4. If response_format='json', parse and optionally validate output
        5. Return structured dict with response + audit metadata

    Determinism guarantee:
        - temperature=0 by default (sampling-free)
        - seed passed to client_fn for providers that support it
        - prompt_fingerprint deterministic for same (template + variables + model + temp + seed)
        - client_fn is injected by caller; oskill performs no HTTP

    Design: oskill.llm.* are pure with respect to caller-provided client_fn.
    The client_fn is the I/O boundary (Layer 4). This mirrors scipy.optimize.minimize(fun, x0):
    scipy is pure; fun is caller-provided.

    Reference: arxiv 2601.15322 (Replayable Financial Agents, 2026).
    Reference: arxiv 2603.22567 (TrustTrade, 2026), determinism + faithfulness framework.

    Parameters
    ----------
    prompt_template : str
        Prompt template with {variable} placeholders.
    variables : dict
        Values for all template placeholders. Missing keys raise KeyError.
    client_fn : callable
        Layer 4 provided function: (messages, model, **kwargs) -> dict.
        Must return dict with keys: 'content', 'stop_reason', 'input_tokens', 'output_tokens'.
    model : str
        Model identifier (e.g. 'claude-opus-4-7').
    temperature : float
        Sampling temperature. 0.0 for true determinism. Values > 0 produce a warning.
    seed : int or None
        Random seed, passed to client_fn.
    max_tokens : int
        Maximum response tokens.
    response_format : {'text', 'json'}
        Expected response format.
    json_schema : dict or None
        If provided, validate JSON response against this schema.

    Returns
    -------
    dict with keys: 'response', 'prompt_rendered', 'prompt_fingerprint', 'model',
    'temperature', 'seed', 'response_format', 'metadata', 'timestamp_called'.

    Raises
    ------
    KeyError
        If variables dict is missing a template placeholder.
    LLMResponseFormatError
        If response_format='json' but response is not valid JSON.
    LLMResponseValidationError
        If json_schema is provided and response fails validation.
    """
    if temperature > 0.0:
        warnings.warn(
            f"temperature={temperature} > 0 reduces determinism. "
            "Use temperature=0 for fully deterministic outputs.",
            UserWarning,
            stacklevel=2,
        )

    # 1. Render prompt (raises KeyError for missing variables)
    prompt_rendered = prompt_template.format(**variables)

    # 2. Compute fingerprint (oprim calls: canonical_json + sha256_hash)
    audit_payload: dict[str, Any] = {
        "template": prompt_template,
        "variables": variables,
        "model": model,
        "temperature": temperature,
        "seed": seed,
    }
    fingerprint = sha256_hash(canonical_json(audit_payload))

    # 3. Call client_fn with deterministic parameters
    messages = [{"role": "user", "content": prompt_rendered}]
    kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if seed is not None:
        kwargs["seed"] = seed

    client_result = client_fn(messages, model, **kwargs)

    raw_content = client_result.get("content", "")

    # 4. Parse JSON response if requested
    if response_format == "json":
        try:
            response = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMResponseFormatError(
                f"Expected JSON response but got: {raw_content!r}"
            ) from exc

        if json_schema is not None:
            _validate_json_schema(response, json_schema)
    else:
        response = raw_content

    # 5. Build metadata
    metadata = {
        "input_tokens": client_result.get("input_tokens"),
        "output_tokens": client_result.get("output_tokens"),
        "stop_reason": client_result.get("stop_reason"),
    }

    timestamp = datetime.now(UTC).isoformat()

    return {
        "response": response,
        "prompt_rendered": prompt_rendered,
        "prompt_fingerprint": fingerprint,
        "model": model,
        "temperature": temperature,
        "seed": seed,
        "response_format": response_format,
        "metadata": metadata,
        "timestamp_called": timestamp,
    }


def _validate_json_schema(obj: Any, schema: dict) -> None:
    """Minimal inline JSON schema validator (subset of JSON Schema draft-07).

    Validates required fields and basic types without external jsonschema library.
    For full RFC compliance, callers should use jsonschema.validate() at Layer 4.
    """
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(obj, dict):
            raise LLMResponseValidationError(f"Expected JSON object, got {type(obj).__name__}")
        required = schema.get("required", [])
        for key in required:
            if key not in obj:
                raise LLMResponseValidationError(f"Required field missing: {key!r}")
    elif schema_type == "array":
        if not isinstance(obj, list):
            raise LLMResponseValidationError(f"Expected JSON array, got {type(obj).__name__}")
    elif schema_type == "string":
        if not isinstance(obj, str):
            raise LLMResponseValidationError(f"Expected string, got {type(obj).__name__}")
    elif schema_type == "number":
        if not isinstance(obj, (int, float)):
            raise LLMResponseValidationError(f"Expected number, got {type(obj).__name__}")
