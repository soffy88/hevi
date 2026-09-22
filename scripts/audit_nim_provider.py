#!/usr/bin/env python3
"""Sanitized NIM provider-resolution audit; sends one bounded real request."""

from __future__ import annotations

import json
import os
import re

import httpx

from hevi.providers.nim_caller import DEFAULT_NIM_MODEL, _nim_keys


def _safe_body(text: str) -> dict[str, str]:
    text = re.sub(r"nvapi-[A-Za-z0-9_-]+", "[REDACTED]", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return {str(k): str(v)[:300] for k, v in value.items() if k not in {"token", "api_key"}}
    except json.JSONDecodeError:
        pass
    return {"message": text[:300]}


def main() -> int:
    model = os.getenv("HEVI_NIM_MODEL", os.getenv("NIM_MODEL", DEFAULT_NIM_MODEL))
    endpoint = "https://integrate.api.nvidia.com/v1/chat/completions"
    body = {"model": model, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 8}
    result = {
        "REQUESTED_PROVIDER": "NIM", "REQUESTED_MODEL": model,
        "REQUESTED_FUNCTION": "chat.completions", "RESOLVED_PROVIDER": "NIM",
        "RESOLVED_MODEL": model, "RESOLVED_FUNCTION": "chat.completions",
        "ENDPOINT": endpoint, "ACCOUNT_SCOPE": "Bearer account (redacted)",
    }
    key = (_nim_keys() or [""])[0]
    if not key:
        result.update(HTTP_STATUS=None, PROVIDER_ERROR_CODE="MISSING_CREDENTIAL", PROVIDER_ERROR_BODY_SANITIZED={})
    else:
        try:
            response = httpx.post(endpoint, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=20)
            safe = _safe_body(response.text)
            result.update(HTTP_STATUS=response.status_code, PROVIDER_ERROR_CODE=safe.get("code") or safe.get("status") or (f"HTTP_{response.status_code}" if response.is_error else None), PROVIDER_ERROR_BODY_SANITIZED=safe)
        except httpx.HTTPError as exc:
            result.update(HTTP_STATUS=None, PROVIDER_ERROR_CODE=type(exc).__name__, PROVIDER_ERROR_BODY_SANITIZED={"message": type(exc).__name__})
    result["NETWORK_ERROR"] = result["HTTP_STATUS"] is None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["NETWORK_ERROR"] and not result.get("PROVIDER_ERROR_CODE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
