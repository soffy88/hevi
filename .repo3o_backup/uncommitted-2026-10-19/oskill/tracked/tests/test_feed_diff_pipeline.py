"""Tests for oskill.feed_diff_pipeline."""

from __future__ import annotations

from unittest.mock import patch

from oskill.feed_diff_pipeline import feed_diff_pipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ITEM_A = {
    "title": "Alpha",
    "link": "http://ex.com/a",
    "description": "desc a",
    "pub_date": None,
    "guid": "guid-a",
}
_ITEM_B = {
    "title": "Beta",
    "link": "http://ex.com/b",
    "description": "desc b",
    "pub_date": None,
    "guid": "guid-b",
}
_ITEM_C = {
    "title": "Gamma",
    "link": "http://ex.com/c",
    "description": "desc c",
    "pub_date": None,
    "guid": "guid-c",
}

_RSS_RESULT_AB = {
    "feed_title": "Test Feed",
    "feed_url": "http://ex.com/rss",
    "items": [_ITEM_A, _ITEM_B],
    "item_count": 2,
    "error": None,
}

_RSS_RESULT_BC = {
    "feed_title": "Test Feed",
    "feed_url": "http://ex.com/rss",
    "items": [_ITEM_B, _ITEM_C],
    "item_count": 2,
    "error": None,
}

_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <id>http://ex.com/atom</id>
  <entry>
    <title>Atom Item 1</title>
    <id>atom-id-1</id>
    <link href="http://ex.com/atom/1"/>
    <summary>Summary 1</summary>
  </entry>
</feed>
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_previous_items_all_new():
    """When previous_items is empty, all fetched items are new."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_AB):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss", previous_items=[])
    assert out["error"] is None
    assert len(out["new_items"]) == 2
    assert out["total_new"] == 2


def test_same_previous_no_new_items():
    """When previous snapshot equals current fetch, no new items."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_AB):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss", previous_items=[_ITEM_A, _ITEM_B])
    assert out["error"] is None
    assert out["new_items"] == []
    assert out["total_new"] == 0


def test_one_new_item_detected():
    """When one new item appears, total_new == 1."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_BC):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss", previous_items=[_ITEM_B])
    assert out["error"] is None
    assert out["total_new"] == 1
    assert out["new_items"][0]["guid"] == "guid-c"


def test_removed_items_populated():
    """When an item disappears from feed, it appears in removed_items."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_BC):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss", previous_items=[_ITEM_A, _ITEM_B])
    assert out["error"] is None
    removed_guids = [i["guid"] for i in out["removed_items"]]
    assert "guid-a" in removed_guids


def test_feed_title_extracted():
    """feed_title is returned from the RSS result."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_AB):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss")
    assert out["feed_title"] == "Test Feed"


def test_total_new_equals_len_new_items():
    """total_new must equal len(new_items)."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_AB):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss", previous_items=[])
    assert out["total_new"] == len(out["new_items"])


def test_error_none_on_success():
    """error is None when feed fetch succeeds."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_AB):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss")
    assert out["error"] is None


def test_atom_format_uses_parse_atom_feed():
    """feed_format='atom' takes the Atom parse path."""
    atom_result = {
        "feed_title": "Atom Feed",
        "feed_id": "http://ex.com/atom",
        "updated": None,
        "items": [
            {
                "title": "Atom Item 1",
                "id": "atom-id-1",
                "link": "http://ex.com/atom/1",
                "summary": "Summary 1",
                "updated": None,
                "author": None,
            },
        ],
        "item_count": 1,
        "error": None,
    }

    # Patch the urllib.request.urlopen to avoid real HTTP calls in Atom path
    class _FakeResp:
        def read(self):
            return _ATOM_XML.encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with (
        patch("oskill.feed_diff_pipeline.parse_atom_feed", return_value=atom_result) as mock_atom,
        patch("urllib.request.urlopen", return_value=_FakeResp()),
    ):
        out = feed_diff_pipeline(
            feed_url="http://ex.com/atom", feed_format="atom", previous_items=[]
        )

    mock_atom.assert_called_once()
    assert out["error"] is None
    assert out["total_new"] == 1
    assert out["feed_title"] == "Atom Feed"


def test_none_previous_treated_as_empty():
    """previous_items=None (default) treats all items as new."""
    with patch("oskill.feed_diff_pipeline.fetch_rss_feed", return_value=_RSS_RESULT_AB):
        out = feed_diff_pipeline(feed_url="http://ex.com/rss")
    assert out["total_new"] == 2
