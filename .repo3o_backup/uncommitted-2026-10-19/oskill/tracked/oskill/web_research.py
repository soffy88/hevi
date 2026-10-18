"""K-16 web_research — multi-source web research with LLM synthesis.

Composes oprim:
    - http_fetch
    - html_to_markdown
    - extract_main_content
    - validate_url
    - (LLMCaller Protocol for synthesis)

Note: web_search_query oprim not available; caller/parent provides URLs
or this function performs basic search via http_fetch with search engine URL.
IO-orchestration (HTTP + LLM). Not used as sub-call by sibling oskills.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, cast
from urllib.parse import quote_plus

from oprim import extract_main_content, html_to_markdown, http_fetch, validate_url

from ._hc_types import ResearchResult


class LLMCaller(Protocol):
    async def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]: ...


async def _fetch_and_extract(url: str) -> str:
    """Fetch URL and extract main text content."""
    try:
        raw = await http_fetch(url)
        if isinstance(raw, bytes):
            html = raw.decode("utf-8", errors="replace")
        else:
            html = str(raw)
        md = html_to_markdown(html)
        return cast(str, extract_main_content(md))[:3000]
    except Exception:
        return ""


async def web_research(
    query: str,
    *,
    caller: LLMCaller,
    max_sources: int = 5,
) -> ResearchResult:
    """Research *query* by fetching and synthesising web sources.

    Composes: http_fetch, html_to_markdown, extract_main_content,
              validate_url, caller (LLM injection).

    Args:
        query: Research query string.
        caller: LLM caller for synthesis.
        max_sources: Maximum number of sources to fetch.

    Returns:
        ResearchResult with sources, summary, and confidence.

    Raises:
        ValueError: If query is empty.
    """
    if not query:
        raise ValueError("query must not be empty")

    # Try DuckDuckGo HTML search (no API key needed for basic results)
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    sources: list[str] = []
    content_chunks: list[str] = []

    # Fetch search results page
    search_html = ""
    try:
        raw = await http_fetch(search_url, headers={"User-Agent": "Mozilla/5.0"})
        search_html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    except Exception:
        pass

    # Extract URLs from search results (simple regex approach)
    import re

    url_pattern = re.compile(r'href="(https?://[^"]+)"')
    found_urls = url_pattern.findall(search_html)

    # Filter and deduplicate
    seen: set[str] = set()
    for url in found_urls:
        if validate_url(url) and url not in seen and "duckduckgo" not in url:
            seen.add(url)
            sources.append(url)
        if len(sources) >= max_sources:
            break

    # Concurrent fetch of sources
    if sources:
        tasks = [_fetch_and_extract(url) for url in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        content_chunks = [r for r in results if isinstance(r, str) and r.strip()]

    if not content_chunks:
        return ResearchResult(query=query, sources=sources, summary="", confidence=0.0)

    # LLM synthesis
    combined = "\n\n---\n\n".join(content_chunks[:max_sources])
    prompt_msgs = [
        {
            "role": "user",
            "content": (
                f"Research question: {query}\n\n"
                f"Sources:\n{combined}\n\n"
                "Provide a concise synthesis of the key findings."
            ),
        }
    ]

    try:
        response = await caller(messages=prompt_msgs, max_tokens=1024)
        content = response.get("content", "")
        if isinstance(content, list):
            summary = " ".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            summary = str(content)
        confidence = min(1.0, len(content_chunks) / max_sources)
    except Exception:
        raise

    return ResearchResult(
        query=query,
        sources=sources,
        summary=summary,
        confidence=confidence,
    )
