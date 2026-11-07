"""oskill.researcher_workflow — Automated research workflow: search → fetch → extract.

3O layer: oskill (≥2 oprim composition, stateless).

Internal oprim composition:
    - oprim.searxng_search: find relevant sources via searxng
    - oprim.url_fetch_ssrf_safe: fetch each result URL safely
    - oprim.concept_extractor: extract key concepts from fetched content
"""

from __future__ import annotations

from oprim import concept_extractor, searxng_search, url_fetch_ssrf_safe


def researcher_workflow(
    *,
    query: str,
    searxng_url: str,
    max_sources: int = 5,
    fetch_content: bool = True,
    extract_concepts: bool = True,
    timeout: int = 10,
) -> dict:
    """Research a query: search → optionally fetch source content → extract concepts.

    Args:
        query: Research question or topic.
        searxng_url: searxng instance base URL.
        max_sources: Maximum URLs to fetch and analyze.
        fetch_content: If True, fetch each result's full page content.
        extract_concepts: If True, extract concepts from fetched content.
        timeout: HTTP timeout per request.

    Returns:
        {
            query: str,
            sources: [{title, url, snippet, concepts: list[str], fetch_error: str|None}],
            all_concepts: list[str],   # deduplicated union across all sources
            total_sources: int,
            error: str | None,
        }
    """
    result: dict = {
        "query": query,
        "sources": [],
        "all_concepts": [],
        "total_sources": 0,
        "error": None,
    }

    # 1. Search via searxng_search oprim
    search_result = searxng_search(
        query=query,
        searxng_url=searxng_url,
        max_results=max_sources,
        timeout=timeout,
    )
    if search_result["error"]:
        result["error"] = f"search failed: {search_result['error']}"
        return result

    all_concepts: set[str] = set()
    sources = []

    for item in search_result["results"][:max_sources]:
        source = {
            "title": item["title"],
            "url": item["url"],
            "snippet": item["content"],
            "concepts": [],
            "fetch_error": None,
        }

        page_text = item["content"]  # fallback: use snippet

        if fetch_content and item["url"]:
            # 2. Fetch full page via url_fetch_ssrf_safe oprim
            fetch = url_fetch_ssrf_safe(url=item["url"], timeout=timeout, max_bytes=64 * 1024)
            if fetch["error"]:
                source["fetch_error"] = fetch["error"]
            else:
                page_text = fetch["body_text"] or page_text

        if extract_concepts and page_text:
            # 3. Extract concepts via concept_extractor oprim
            cx = concept_extractor(text=page_text, max_concepts=10)
            source["concepts"] = cx["concepts"]
            all_concepts.update(cx["concepts"])

        sources.append(source)

    result["sources"] = sources
    result["all_concepts"] = sorted(all_concepts)
    result["total_sources"] = len(sources)
    return result
