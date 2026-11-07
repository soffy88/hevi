"""Public web search via SearXNG metasearch engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from oprim._logging import log
from oprim.external.clients.searxng_client import SearxngClient, WebSearchResult


@dataclass
class WebSearchResponse:
    query: str
    results: list[WebSearchResult] = field(default_factory=list)
    result_count: int = 0


async def web_search_augmented(
    query: str,
    max_results: int = 10,
    language: str = "auto",
    categories: list[str] | None = None,
) -> WebSearchResponse:
    """Search the public web via local SearXNG instance (localhost:8080).

    Complements hybrid_search (user's knowledge library) with public web results.
    No GPU required — SearXNG is a lightweight metasearch aggregator.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return (capped at 50).
        language: BCP47 language code (e.g. "zh-CN", "en") or "auto".
        categories: SearXNG category filters (e.g. ["general", "science"]).

    Returns:
        WebSearchResponse with structured result list.
    """
    if not query.strip():
        raise ValueError("query must not be empty")

    max_results = min(max_results, 50)
    client = SearxngClient()
    try:
        results = await client.search(
            query=query,
            max_results=max_results,
            language=language,
            categories=categories,
        )
    finally:
        await client.close()

    log.info(
        "web_search_augmented.done",
        query=query[:80],
        results=len(results),
    )
    return WebSearchResponse(
        query=query,
        results=results,
        result_count=len(results),
    )
