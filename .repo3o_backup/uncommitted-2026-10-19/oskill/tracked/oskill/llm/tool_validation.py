"""Tool call validator — validates LLM-generated tool calls against JSON Schema."""

from __future__ import annotations

from typing import Any

from oprim import canonical_json

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _check_type(value: Any, expected_type: str) -> bool:
    """Return True if value matches expected JSON Schema type."""
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "null":
        return value is None
    return True  # unknown type — pass through


def _coerce_value(value: Any, expected_type: str) -> tuple[bool, Any]:
    """Attempt safe type coercion. Returns (success, coerced_value)."""
    if _check_type(value, expected_type):
        return True, value

    if expected_type == "integer" and isinstance(value, str):
        try:
            return True, int(value)
        except (ValueError, TypeError):
            return False, value

    if expected_type == "number" and isinstance(value, str):
        try:
            return True, float(value)
        except (ValueError, TypeError):
            return False, value

    if expected_type == "boolean" and isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True, True
        if value.lower() in ("false", "0", "no"):
            return True, False
        return False, value

    if expected_type == "string" and not isinstance(value, (dict, list)):
        return True, str(value)

    return False, value


def tool_call_validator(
    tool_call: dict,
    tool_schema: dict,
    *,
    strict: bool = True,
    coerce_types: bool = False,
) -> dict[str, Any]:
    """Validate an LLM-generated tool call against a JSON Schema tool definition.

    Workflow:
        1. Parse tool_call: extract 'name' and 'arguments' (or 'input' for Anthropic-style)
        2. Check tool_call['name'] matches tool_schema['name']
        3. Validate arguments against tool_schema['parameters'] (required fields, types)
        4. If coerce_types=True: attempt safe coercions (str→int, str→float, str→bool)
        5. In strict mode: extra keys in arguments are errors; in non-strict: warnings

    Parameters
    ----------
    tool_call : dict
        LLM-generated tool call. Supports both OpenAI-style ('arguments') and
        Anthropic-style ('input') key names.
    tool_schema : dict
        Tool schema with keys: 'name', 'parameters' (JSON Schema object).
    strict : bool
        If True, extra argument keys are errors. If False, they produce warnings.
    coerce_types : bool
        If True, attempt safe type coercions (e.g., str "42" → int 42).

    Returns
    -------
    dict with keys:
        - 'valid': bool
        - 'errors': list of {path, message, expected, actual}
        - 'warnings': list
        - 'normalized_arguments': dict
        - 'tool_name': str
    """
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1. Extract name and arguments from tool_call
    tool_name = tool_call.get("name", "")

    # Support both OpenAI-style 'arguments' and Anthropic-style 'input'
    if "input" in tool_call:
        raw_arguments = tool_call["input"]
    else:
        raw_arguments = tool_call.get("arguments", {})

    # Handle JSON string arguments (OpenAI format)
    if isinstance(raw_arguments, str):
        import json

        try:
            raw_arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError):
            raw_arguments = {}

    if not isinstance(raw_arguments, dict):
        raw_arguments = {}

    # 2. Check name matches schema
    schema_name = tool_schema.get("name", "")
    if tool_name != schema_name:
        errors.append(
            {
                "path": "name",
                "message": f"Tool name mismatch: got '{tool_name}', expected '{schema_name}'",
                "expected": schema_name,
                "actual": tool_name,
            }
        )

    parameters = tool_schema.get("parameters", {})
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    # Work with a copy for normalization
    normalized: dict[str, Any] = dict(raw_arguments)

    # 3. Validate required fields
    for field in required:
        if field not in normalized:
            errors.append(
                {
                    "path": f"arguments.{field}",
                    "message": f"Required field missing: '{field}'",
                    "expected": "present",
                    "actual": "missing",
                }
            )

    # 4. Validate types + optional coercion
    for field, value in list(normalized.items()):
        if field not in properties:
            # Extra field handling
            msg = f"Unexpected argument key: '{field}'"
            if strict:
                errors.append(
                    {
                        "path": f"arguments.{field}",
                        "message": msg,
                        "expected": "not present",
                        "actual": type(value).__name__,
                    }
                )
            else:
                warnings.append(msg)
            continue

        field_schema = properties[field]
        expected_type = field_schema.get("type")

        if expected_type is None:
            continue

        if coerce_types:
            success, coerced = _coerce_value(value, expected_type)
            if success:
                normalized[field] = coerced
            else:
                errors.append(
                    {
                        "path": f"arguments.{field}",
                        "message": (
                            f"Type error for '{field}': cannot coerce "
                            f"{type(value).__name__!r} to {expected_type!r}"
                        ),
                        "expected": expected_type,
                        "actual": type(value).__name__,
                    }
                )
        else:
            if not _check_type(value, expected_type):
                errors.append(
                    {
                        "path": f"arguments.{field}",
                        "message": (
                            f"Type error for '{field}': expected {expected_type!r}, "
                            f"got {type(value).__name__!r}"
                        ),
                        "expected": expected_type,
                        "actual": type(value).__name__,
                    }
                )

    # Normalize via oprim.canonical_json for consistent key ordering
    # (parse back to dict since canonical_json returns a string)
    import json as _json

    try:
        normalized_arguments = _json.loads(canonical_json(normalized))
    except Exception:
        normalized_arguments = normalized

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "normalized_arguments": normalized_arguments,
        "tool_name": tool_name,
    }
