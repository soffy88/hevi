"""oskill.threeo_ingester — Invoke 3O omodul and extract InsightContext.

Example:
    >>> from oskill.threeo_ingester import threeo_ingester
    >>> ctx = await threeo_ingester(omodul_function="behavioral_portfolio_workflow", ...)

Raises:
    ThreeOIngestError: Ingestion failed.
    ThreeOSetupError: omodul import failed.
"""

from __future__ import annotations

import importlib
import json
from typing import Any

from oskill._schemas import InsightContext


class ThreeOIngestError(Exception):
    """3O ingestion failed."""


class ThreeOSetupError(ThreeOIngestError):
    """omodul import or setup failed."""


async def threeo_ingester(
    *,
    omodul_function: str,
    omodul_config: dict[str, Any],
    llm: Any,
) -> InsightContext:
    """Invoke a 3O omodul function and extract insights via LLM.

    Args:
        omodul_function: Fully qualified omodul function name (e.g. 'omodul.behavioral.workflow').
        omodul_config: Configuration dict to pass to the omodul.
        llm: LLMCaller protocol instance for insight extraction.

    Returns:
        InsightContext with key findings, charts, and related concepts.

    Raises:
        ThreeOSetupError: If omodul cannot be imported.
        ThreeOIngestError: If execution or LLM extraction fails.

    Example:
        >>> ctx = await threeo_ingester(omodul_function="omodul.x.workflow", ...)
    """
    # Import and invoke omodul
    parts = omodul_function.rsplit(".", 1)
    if len(parts) != 2:
        raise ThreeOSetupError(f"Invalid omodul_function format: {omodul_function}")

    module_path, func_name = parts
    try:
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)
    except (ImportError, AttributeError) as exc:
        raise ThreeOSetupError(f"Cannot import {omodul_function}: {exc}") from exc

    try:
        raw_report = func(omodul_config)
    except Exception as exc:
        raise ThreeOIngestError(f"omodul execution failed: {exc}") from exc

    # LLM extraction
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Extract insights from this report. Return JSON: "
                '{"topic", "key_findings": [], "charts": [], '
                '"related_concepts": [], "source_omodul", "raw_report": {}}'
            ),
        },
        {"role": "user", "content": json.dumps(raw_report, default=str)[:8000]},
    ]

    result = llm(messages=messages)
    content = result.get("content", "")

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ThreeOIngestError(f"LLM returned invalid JSON: {content[:200]}") from exc

    data.setdefault("source_omodul", omodul_function)
    data.setdefault("raw_report", raw_report if isinstance(raw_report, dict) else {})

    try:
        return InsightContext.model_validate(data)
    except Exception as exc:
        raise ThreeOIngestError(f"InsightContext validation failed: {exc}") from exc
