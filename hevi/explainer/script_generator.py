"""Public script-generation facade for Explainer Master v8.

The provider remains injectable so research/model failures are returned as the
same structured capability errors used by the API; this module contains no
fallback or canned storyboard.
"""

from __future__ import annotations

from typing import Any

from hevi.explainer.contracts import ExplainerResearchRequest, ExplainerServiceResult
from hevi.explainer.research import research_and_generate


async def generate_script_versions(
    topic_or_url: str,
    research: dict[str, Any],
    *,
    generator: Any,
) -> ExplainerServiceResult:
    """Generate and validate exactly three visual-scaffold script versions."""
    return await research_and_generate(
        ExplainerResearchRequest(topic_or_url=topic_or_url),
        researcher=lambda _topic: research,
        script_generator=generator,
    )


__all__ = ["generate_script_versions"]
