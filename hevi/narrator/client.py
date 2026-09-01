"""Thin wrapper around narrator-ai-cli. No network unless the binary + key exist."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

ALLOWED: dict[str, tuple[str, ...]] = {
    "material-list": ("material", "list", "--json"),
    "user-balance": ("user", "balance"),
    "bgm-list": ("bgm", "list", "--json"),
    "dubbing-list": ("dubbing", "list", "--json"),
    "narration-styles": ("task", "narration-styles", "--json"),
    "search-movie": ("task", "search-movie"),
}


class NarratorUnavailable(RuntimeError):
    """CLI or API key missing. Callers must surface this, never invent results."""


def narrator_status() -> dict[str, Any]:
    binary = shutil.which("narrator-ai-cli")
    key = (os.environ.get("NARRATOR_APP_KEY") or "").strip()
    return {
        "cli": binary is not None,
        "binary": binary,
        "app_key": bool(key),
        "hint": _hint(binary is not None, bool(key)),
        "verbs": sorted(ALLOWED),
    }


def _hint(has_cli: bool, has_key: bool) -> str:
    if has_cli and has_key:
        return "ready"
    parts = []
    if not has_cli:
        parts.append(
            'pip install "narrator-ai-cli @ git+https://github.com/NarratorAI-Studio/narrator-ai-cli.git"'
        )
    if not has_key:
        parts.append("export NARRATOR_APP_KEY=...  (向 NarratorAI-Studio 申请)")
    return "；".join(parts)


def run_narrator(verb: str, extra: list[str] | None = None, *, timeout: float = 60.0) -> dict[str, Any]:
    status = narrator_status()
    if not status["cli"] or not status["app_key"]:
        raise NarratorUnavailable(status["hint"])
    if verb not in ALLOWED:
        raise ValueError(f"verb 不在白名单: {verb}；允许 {sorted(ALLOWED)}")
    cmd = [str(status["binary"]), *ALLOWED[verb], *(extra or [])]
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ},
    )
    stdout = completed.stdout.strip()
    payload: Any
    try:
        payload = json.loads(stdout) if stdout.startswith(("{", "[")) else stdout
    except json.JSONDecodeError:
        payload = stdout
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or stdout or f"exit {completed.returncode}")
    return {"verb": verb, "ok": True, "result": payload}
