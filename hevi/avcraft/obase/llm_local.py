"""本地 Ollama 适配。只允许本地端点，禁止任何付费云 key。"""

from __future__ import annotations

import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("HEVI_OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_LLM = os.environ.get("HEVI_AVCRAFT_LLM", "llama3.2:3b")


def ollama_generate(
    prompt: str,
    model: str | None = None,
    timeout: float = 300.0,
    temperature: float = 0.1,
    fmt: str | None = None,
) -> str:
    body = {
        "model": model or DEFAULT_LLM,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if fmt:
        body["format"] = fmt
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"]
