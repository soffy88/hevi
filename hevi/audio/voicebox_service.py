"""Voicebox adapter for HEVI's generic audio provider contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hevi.explainer.voicebox_client import synthesize


async def voicebox_synthesize(
    *,
    script: list[Any],
    output_path: Path,
    emotion: str | None = None,
    **_kwargs: Any,
) -> Path:
    """Synthesize generic HEVI lines through one Voicebox profile."""
    text = "\n".join(str(getattr(line, "text", "")).strip() for line in script).strip()
    if not text:
        raise ValueError("Voicebox synthesis requires non-empty text")
    await synthesize(text, output_path, instruct=emotion or None)
    return output_path

