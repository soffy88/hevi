"""Tests for oskill.web_search_augmented."""

from __future__ import annotations

import json
from unittest.mock import patch

from oskill.web_search_augmented import web_search_augmented

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEARXNG_RESULTS = {
    "results": [
        {
            "title": "Alpha result",
            "url": "http://ex.com/a",
            "content": "alpha content about topic",
            "score": 1.0,
        },
        {
            "title": "Beta result",
            "url": "http://ex.com/b",
            "content": "beta content something else",
            "score": 0.5,
        },
        {
            "title": "Gamma result",
            "url": "http://ex.com/c",
            "content": "gamma unrelated info",
            "score": 0.2,
        },
    ]
}

_FETCH_OK = {
    "url": "http://searxng.local/search?q=test&format=json",
    "status_code": 200,
    "content_type": "application/json",
    "body_bytes": json.dumps(_SEARXNG_RESULTS).encode(),
    "body_text": json.dumps(_SEARXNG_RESULTS),
    "error": None,
}

_FETCH_ERR = {
    "url": "http://bad.local/search",
    "status_code": None,
    "content_type": None,
    "body_bytes": b"",
    "body_text": None,
    "error": "ssrf_blocked",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_searxng_url_stub_mode():
    """Empty searxng_url must return provider='stub' and empty results."""
    out = web_search_augmented(query="hello", searxng_url="")
    assert out["provider"] == "stub"
    assert out["results"] == []
    assert out["error"] is None


def test_query_in_result_dict():
    """query field must echo the input query."""
    out = web_search_augmented(query="my query", searxng_url="")
    assert out["query"] == "my query"


def test_total_equals_len_results():
    """total must equal len(results) at all times."""
    with patch("oskill.web_search_augmented.url_fetch_ssrf_safe", return_value=_FETCH_OK):
        out = web_search_augmented(query="alpha", searxng_url="http://searxng.local")
    assert out["total"] == len(out["results"])


def test_rerank_true_calls_bm25_path():
    """With rerank=True, results should be ordered by BM25 score against query."""
    with patch("oskill.web_search_augmented.url_fetch_ssrf_safe", return_value=_FETCH_OK):
        out = web_search_augmented(query="alpha", searxng_url="http://searxng.local", rerank=True)
    assert out["error"] is None
    # 'alpha' should rank first because its snippet contains 'alpha'
    assert out["results"][0]["url"] == "http://ex.com/a"


def test_error_none_in_stub_mode():
    """error is None when stub mode is used (no fetch attempted)."""
    out = web_search_augmented(query="test", searxng_url="")
    assert out["error"] is None


def test_max_results_limits_output():
    """max_results=1 must return at most 1 result."""
    with patch("oskill.web_search_augmented.url_fetch_ssrf_safe", return_value=_FETCH_OK):
        out = web_search_augmented(query="alpha", searxng_url="http://searxng.local", max_results=1)
    assert len(out["results"]) <= 1
    assert out["total"] <= 1


def test_results_have_required_keys():
    """Each result dict must have title, url, snippet, score keys."""
    with patch("oskill.web_search_augmented.url_fetch_ssrf_safe", return_value=_FETCH_OK):
        out = web_search_augmented(query="alpha", searxng_url="http://searxng.local")
    assert out["error"] is None
    for item in out["results"]:
        assert "title" in item
        assert "url" in item
        assert "snippet" in item
        assert "score" in item


def test_invalid_searxng_url_error_set_gracefully():
    """When fetch returns an error, result error is set and results are empty."""
    with patch("oskill.web_search_augmented.url_fetch_ssrf_safe", return_value=_FETCH_ERR):
        out = web_search_augmented(query="test", searxng_url="http://bad.local")
    assert out["error"] == "ssrf_blocked"
    assert out["results"] == []


def test_rerank_false_skips_bm25():
    """With rerank=False, bm25_search should not be called."""
    with (
        patch("oskill.web_search_augmented.url_fetch_ssrf_safe", return_value=_FETCH_OK),
        patch("oskill.web_search_augmented.bm25_search") as mock_bm25,
    ):
        out = web_search_augmented(query="alpha", searxng_url="http://searxng.local", rerank=False)
    mock_bm25.assert_not_called()
    assert out["error"] is None
    assert out["total"] == 3
